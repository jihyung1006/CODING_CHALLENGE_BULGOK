import os
import io
import json
from datetime import datetime, timezone, timedelta
import streamlit as st
import qrcode
from PIL import Image
import google.generativeai as genai
import extra_streamlit_components as stx

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore, auth

# =========================================================
# 🔑 KST (한국 표준시 UTC+9) 시간 함수 설정
# =========================================================
KST = timezone(timedelta(hours=9))

def get_kst_now():
    return datetime.now(KST)

# =========================================================
# 🔑 API KEY & Firebase 초기화
# =========================================================
API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not firebase_admin._apps:
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 초기화 오류: {e}")

db = firestore.client()

# ---------------------------------------------------------
# 1. 페이지 레이아웃 및 쿠키 매니저 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI 식단 분석 코치",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# 쿠키 매니저 초기화
cookie_manager = stx.CookieManager()

if "user" not in st.session_state:
    st.session_state["user"] = None

# ---------------------------------------------------------
# 🍪 쿠키를 이용한 자동 로그인 체크
# ---------------------------------------------------------
saved_uid = cookie_manager.get(cookie="auth_uid")
saved_email = cookie_manager.get(cookie="auth_email")

# 세션이 없지만 쿠키에 정보가 남아 있는 경우 자동 로그인
if not st.session_state["user"] and saved_uid and saved_email:
    st.session_state["user"] = {"uid": saved_uid, "email": saved_email}

# ---------------------------------------------------------
# 📱 사이드바 (자동 URL 감지 QR 코드 생성)
# ---------------------------------------------------------
with st.sidebar:
    st.header("📱 모바일 접속 QR")
    
    try:
        host = st.context.headers.get("host", "")
        current_url = f"https://{host}" if host else "https://share.streamlit.io"
    except Exception:
        current_url = "https://share.streamlit.io"

    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(current_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    
    st.image(buf.getvalue(), caption="스마트폰 카메라로 스캔하세요", width=200)
    st.caption(f"접속 주소: {current_url}")

# ---------------------------------------------------------
# 2. 로그인 / 회원가입 / 게스트 입장 화면
# ---------------------------------------------------------
if not st.session_state["user"]:
    st.title("🥗 AI 식단 분석 코치")
    st.subheader("로그인 후 식단을 기록하거나, 게스트로 체험해 보세요!")

    auth_tab1, auth_tab2 = st.tabs(["🔑 로그인", "📝 회원가입"])

    with auth_tab1:
        login_email = st.text_input("이메일", key="login_email")
        login_password = st.text_input("비밀번호", type="password", key="login_pwd")
        remember_me = st.checkbox("자동 로그인 (로그인 상태 유지)", value=True)
        
        col_login, col_guest = st.columns(2)
        with col_login:
            if st.button("로그인", type="primary", use_container_width=True):
                try:
                    user = auth.get_user_by_email(login_email)
                    st.session_state["user"] = {"uid": user.uid, "email": user.email}
                    
                    # 자동 로그인 체크 시 쿠키에 30일간 저장
                    if remember_me:
                        expires_at = datetime.now() + timedelta(days=30)
                        cookie_manager.set("auth_uid", user.uid, expires_at=expires_at)
                        cookie_manager.set("auth_email", user.email, expires_at=expires_at)
                    
                    st.success(f"환영합니다, {user.email}님!")
                    st.rerun()
                except Exception:
                    st.error("로그인 실패: 이메일 또는 비밀번호를 확인하세요.")
        
        with col_guest:
            if st.button("👤 게스트로 이용하기", use_container_width=True):
                st.session_state["user"] = "guest"
                st.rerun()

    with auth_tab2:
        signup_email = st.text_input("이메일 등록", key="signup_email")
        signup_password = st.text_input("비밀번호 (6자리 이상)", type="password", key="signup_pwd")
        if st.button("회원가입 완료", use_container_width=True):
            try:
                user = auth.create_user(email=signup_email, password=signup_password)
                st.success("회원가입 성공! 로그인 탭에서 로그인해 주세요.")
            except Exception as e:
                st.error(f"회원가입 실패: {e}")

    st.stop()

# ---------------------------------------------------------
# 3. 메인 서비스 화면
# ---------------------------------------------------------
st.title("🥗 AI 식단 분석 코치")

if st.session_state["user"] == "guest":
    st.warning("⚠️ 현재 **게스트 모드**로 이용 중입니다. 식단 기록 및 종합 분석 기능이 저장되지 않습니다.")
    if st.button("🔑 로그인/회원가입 하러 가기", type="secondary"):
        st.session_state["user"] = None
        st.rerun()
else:
    st.caption(f"👤 로그인 계정: {st.session_state['user']['email']}")
    if st.button("🚪 로그아웃", type="secondary"):
        st.session_state["user"] = None
        # 로그아웃 시 쿠키 삭제
        cookie_manager.delete("auth_uid")
        cookie_manager.delete("auth_email")
        st.rerun()

main_tab1, main_tab2, main_tab3 = st.tabs(["📸 식단 분석하기", "📂 내 식단 히스토리", "📊 일일 요약 분석"])

# --- TAB 1: 식단 분석 및 저장 ---
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

        btn_label = "🔥 AI 영양 분석 실행 (저장 안 됨)" if st.session_state["user"] == "guest" else "🔥 AI 영양 분석 & DB 저장"
        
        if st.button(btn_label, type="primary", use_container_width=True):
            now_kst = get_kst_now()
            current_hour = now_kst.hour
            
            if 5 <= current_hour < 10:
                meal_type = "아침 식단"
            elif 10 <= current_hour < 16:
                meal_type = "점심 식단"
            elif 16 <= current_hour < 22:
                meal_type = "저녁 식단"
            else:
                meal_type = "야식/간식"

            with st.spinner("AI가 식단을 분석 중입니다..."):
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

                    if st.session_state["user"] != "guest":
                        doc_data = {
                            "uid": st.session_state["user"]["uid"],
                            "date": now_kst.strftime("%Y-%m-%d"),
                            "time": now_kst.strftime("%H:%M:%S"),
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
                    else:
                        st.success("분석 완료! (게스트 모드이므로 저장되지 않았습니다)")

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
                    st.error(f"분석 오류 발생: {e}")

# --- TAB 2: 과거 내 식단 히스토리 ---
with main_tab2:
    if st.session_state["user"] == "guest":
        st.info("🔒 게스트 모드에서는 식단 히스토리가 제공되지 않습니다.")
    else:
        st.subheader("🗓️ 내 저장된 식단 히스토리")
        
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

# --- TAB 3: 하루 종합 분석 보고서 ---
with main_tab3:
    if st.session_state["user"] == "guest":
        st.info("🔒 게스트 모드에서는 일일 요약 분석 보고서가 제공되지 않습니다.")
    else:
        st.subheader("📊 하루 식단 종합 요약 보고서")
        
        selected_date = st.date_input("조회할 날짜를 선택하세요", get_kst_now().date()).strftime("%Y-%m-%d")
        
        meals_ref = db.collection("meals")
        query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).where("date", "==", selected_date).get()
        
        if not query:
            st.warning(f"선택하신 날짜({selected_date})에 등록된 식단 기록이 없습니다.")
        else:
            daily_meals = [doc.to_dict() for doc in query]
            daily_meals.sort(key=lambda x: x.get("time", ""))
            
            total_cal = sum([m.get("total_calories", 0) for m in daily_meals])
            total_carbs = sum([m.get("carbs_g", 0) for m in daily_meals])
            total_protein = sum([m.get("protein_g", 0) for m in daily_meals])
            total_fat = sum([m.get("fat_g", 0) for m in daily_meals])
            
            st.markdown(f"### 📈 {selected_date} 영양 섭취 총계")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("총 칼로리", f"{total_cal} kcal")
            col2.metric("총 탄수화물", f"{total_carbs} g")
            col3.metric("총 단백질", f"{total_protein} g")
            col4.metric("총 지방", f"{total_fat} g")
            
            st.divider()
            
            st.markdown("### 🍽️ 오늘 먹은 식단 타임라인")
            summary_text_list = []
            for m in daily_meals:
                foods_str = ", ".join([f"{f['name']}({f['portion']})" for f in m.get("foods", [])])
                st.write(f"- **[{m.get('meal_type')}]** {foods_str} → `{m.get('total_calories')} kcal`")
                summary_text_list.append(f"- {m.get('meal_type')}: {foods_str} (칼로리: {m.get('total_calories')}kcal, 탄수화물: {m.get('carbs_g')}g, 단백질: {m.get('protein_g')}g, 지방: {m.get('fat_g')}g)")
            
            st.divider()
            
            if st.button("🤖 AI 하루 식단 종합 총평 받기", type="primary", use_container_width=True):
                with st.spinner("하루 식단을 종합 분석하여 보고서를 작성 중입니다..."):
                    try:
                        genai.configure(api_key=API_KEY)
                        model = genai.GenerativeModel('gemini-3.6-flash')
                        
                        daily_summary = "\n".join(summary_text_list)
                        prompt = f"""
                        당신은 수석 영양 코치입니다. 사용자가 오늘 하루 동안 먹은 식단 리스트는 다음과 같습니다:
                        
                        [오늘의 식단 총계]
                        - 총 칼로리: {total_cal} kcal
                        - 총 탄수화물: {total_carbs} g
                        - 총 단백질: {total_protein} g
                        - 총 지방: {total_fat} g
                        
                        [식단 세부 기록]
                        {daily_summary}
                        
                        위 데이터를 바탕으로 사용자의 하루 영양 섭취 상태를 종합적으로 평가하는 보고서를 작성해 주세요.
                        반드시 다음 항목을 포함해서 친절하고 전문적인 어조로 작성해 주세요:
                        1. 📊 오늘 식단 종합 평가 (영양 비율 및 칼로리 적절성)
                        2. 👍 잘한 점 (칭찬할 만한 식습관)
                        3. ⚠️ 아쉬운 점 및 개선 가이드 (부족하거나 과도한 영양소 분석)
                        4. 💡 내일을 위한 식단 추천 팁
                        """
                        
                        response = model.generate_content(prompt)
                        st.markdown("### 📋 AI 영양 코치의 하루 종합 피드백")
                        st.info(response.text)
                    except Exception as e:
                        st.error(f"종합 보고서 생성 중 오류 발생: {e}")
