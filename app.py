import os
import io
import json
from datetime import datetime
import streamlit as st
import qrcode
from PIL import Image
import google.generativeai as genai

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore, auth

# =========================================================
# 🔑 API KEY & Firebase 초기화
# =========================================================
API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

# Firebase 앱 중복 실행 방지 초기화
if not firebase_admin._apps:
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        # Private key 줄바꿈 특수문자 처리
        firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 초기화 오류: {e}")

db = firestore.client()

# ---------------------------------------------------------
# 1. 페이지 레이아웃 및 세션 상태 관리
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI 식단 분석 코치",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

if "user" not in st.session_state:
    st.session_state["user"] = None

# ---------------------------------------------------------
# 2. 로그인 / 회원가입 화면 (비로그인 상태)
# ---------------------------------------------------------
if not st.session_state["user"]:
    st.title("🥗 AI 식단 분석 코치")
    st.subheader("로그인 후 식단 분석 및 개인 기록을 저장해 보세요!")

    auth_tab1, auth_tab2 = st.tabs(["🔑 로그인", "📝 회원가입"])

    with auth_tab1:
        login_email = st.text_input("이메일", key="login_email")
        login_password = st.text_input("비밀번호", type="password", key="login_pwd")
        if st.button("로그인", type="primary", use_container_width=True):
            try:
                user = auth.get_user_by_email(login_email)
                st.session_state["user"] = {"uid": user.uid, "email": user.email}
                st.success(f"환영합니다, {user.email}님!")
                st.rerun()
            except Exception:
                st.error("로그인 실패: 이메일 또는 비밀번호를 확인하세요.")

    with auth_tab2:
        signup_email = st.text_input("이메일 등록", key="signup_email")
        signup_password = st.text_input("비밀번호 (6자리 이상)", type="password", key="signup_pwd")
        if st.button("회원가입 완료", use_container_width=True):
            try:
                user = auth.create_user(email=signup_email, password=signup_password)
                st.success("회원가입 성공! 로그인 탭에서 로그인해 주세요.")
            except Exception as e:
                st.error(f"회원가입 실패: {e}")

    st.stop()  # 로그인 전 하단 기능 접근 차단

# ---------------------------------------------------------
# 3. 로그인 완료 후 화면 (식단 분석 & 히스토리 조회)
# ---------------------------------------------------------
st.title("🥗 AI 식단 분석 코치")
st.caption(f"👤 로그인 계정: {st.session_state['user']['email']}")

if st.button("🚪 로그아웃", type="secondary"):
    st.session_state["user"] = None
    st.rerun()

# 사이드바 (모바일 접속용 QR)
with st.sidebar:
    st.header("📱 모바일 접속 QR 생성")
    public_url = st.text_input("ngrok 또는 배포된 URL 입력", placeholder="https://xxxx.ngrok-free.app")
    if public_url:
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(public_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        st.image(buf.getvalue(), caption="스마트폰 카메라로 스캔하세요", width=200)

main_tab1, main_tab2 = st.tabs(["📸 식단 분석 및 저장", "📂 내 식단 히스토리"])

# --- TAB 1: 분석 및 서버 저장 ---
with main_tab1:
    sub_tab1, sub_tab2 = st.tabs(["📸 카메라 촬영", "🖼️ 앨범에서 선택"])
    img_file = None

    with sub_tab1:
        camera_photo = st.camera_input("음식을 촬영하세요")
        if camera_photo:
            img_file = camera_photo

    with sub_tab2:
        uploaded_photo = st.file_uploader("음식 이미지 파일 선택", type=["jpg", "jpeg", "png"])
        if uploaded_photo:
            img_file = uploaded_photo

    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="분석 대상 이미지", use_container_width=True)

        if st.button("🔥 AI 영양 분석 & DB 저장", type="primary", use_container_width=True):
            current_hour = datetime.now().hour
            if 5 <= current_hour < 10:
                meal_type = "아침 식단"
            elif 10 <= current_hour < 16:
                meal_type = "점심 식단"
            elif 16 <= current_hour < 22:
                meal_type = "저녁 식단"
            else:
                meal_type = "야식/간식"

            with st.spinner("AI 분석 및 Firestore 데이터베이스 저장 중..."):
                try:
                    genai.configure(api_key=API_KEY)
                    model = genai.GenerativeModel('gemini-3.6-flash')

                    prompt = f"""
                    당신은 전문 영양 코치입니다. 전달받은 이미지는 사용자가 **{meal_type}**으로 제출한 식단 사진입니다.
                    
                    반드시 아래 예시와 완전히 똑같은 Pure JSON 형식으로만 응답하세요.

                    {{
                        "meal_type": "{meal_type}",
                        "total_calories": 550,
                        "carbs_g": 65,
                        "protein_g": 30,
                        "fat_g": 15,
                        "foods": [
                            {{"name": "음식이름", "portion": "1공기", "calories": 300}}
                        ],
                        "health_advice": "식단 평가 및 영양 조언 1~2문장"
                    }}
                    """

                    response = model.generate_content([prompt, image])
                    
                    raw_text = response.text.strip()
                    start_idx = raw_text.find("{")
                    end_idx = raw_text.rfind("}") + 1
                    json_str = raw_text[start_idx:end_idx]
                    
                    data = json.loads(json_str)

                    # --- Firebase Firestore DB에 데이터 저장 ---
                    now = datetime.now()
                    doc_data = {
                        "uid": st.session_state["user"]["uid"],
                        "date": now.strftime("%Y-%m-%d"),
                        "time": now.strftime("%H:%M:%S"),
                        "meal_type": data['meal_type'],
                        "total_calories": data['total_calories'],
                        "carbs_g": data['carbs_g'],
                        "protein_g": data['protein_g'],
                        "fat_g": data['fat_g'],
                        "foods": data['foods'],
                        "health_advice": data['health_advice'],
                        "created_at": firestore.SERVER_TIMESTAMP
                    }
                    db.collection("meals").add(doc_data)

                    st.success("분석 완료 및 개인 기록 저장 성공!")
                    st.subheader(f"📌 {data['meal_type']} (총 {data['total_calories']} kcal)")

                    col1, col2, col3 = st.columns(3)
                    col1.metric("탄수화물", f"{data['carbs_g']}g")
                    col2.metric("단백질", f"{data['protein_g']}g")
                    col3.metric("지방", f"{data['fat_g']}g")

                    st.divider()
                    st.markdown("### 🍱 항목별 상세 정보")
                    for food in data['foods']:
                        with st.expander(f"**{food['name']}** ({food['portion']}) - {food['calories']} kcal"):
                            st.write(f"- 추정 칼로리: {food['calories']} kcal")

                    st.divider()
                    st.markdown("### 💡 AI 영양 코치의 조언")
                    st.info(data['health_advice'])

                except Exception as e:
                    st.error(f"분석/저장 오류 발생: {e}")

# --- TAB 2: 과거 내 식단 저장소 ---
with main_tab2:
    st.subheader("🗓️ 내 저장된 식단 히스토리")
    
    # 내 로그인 계정(UID)의 식단 기록만 가져오기
    meals_ref = db.collection("meals")
    query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).get()

    if not query:
        st.info("저장된 식단 기록이 없습니다. 사진을 올려 식단을 기록해 보세요!")
    else:
        meal_list = [doc.to_dict() for doc in query]
        meal_list.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)

        for item in meal_list:
            with st.expander(f"📅 {item.get('date')} [{item.get('meal_type')}] - {item.get('total_calories')} kcal"):
                st.write(f"**시간:** {item.get('time')}")
                st.write(f"**영양성분:** 탄수화물 {item.get('carbs_g')}g | 단백질 {item.get('protein_g')}g | 지방 {item.get('fat_g')}g")
                st.write("**상세 음식:**")
                for f in item.get("foods", []):
                    st.write(f"- {f.get('name')} ({f.get('portion')}): {f.get('calories')} kcal")
                st.caption(f"💡 조언: {item.get('health_advice')}")
