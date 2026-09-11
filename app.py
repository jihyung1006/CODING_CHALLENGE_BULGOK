import os
import io
import json
import time
from datetime import datetime, timezone, timedelta
import streamlit as st
import qrcode
from PIL import Image
import google.generativeai as genai
import extra_streamlit_components as stx
from fpdf import FPDF

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore, auth

# =========================================================
# 🔑 KST (한국 표준시 UTC+9) 시간 설정
# =========================================================
KST = timezone(timedelta(hours=9))

def get_kst_now():
    return datetime.now(KST)

# =========================================================
# 🔑 API KEY & Firebase 초기화
# =========================================================
DEFAULT_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not firebase_admin._apps:
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 연결 오류: {e}")

db = firestore.client()

# =========================================================
# 🤖 AI API 호출 재시도 함수
# =========================================================
def generate_content_with_retry(api_key, model_name, contents, max_retries=3):
    if not api_key:
        raise ValueError("Gemini API 키가 필요해요! 사이드바에서 키를 입력해 주세요.")
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    for attempt in range(max_retries):
        try:
            return model.generate_content(contents)
        except Exception as e:
            err_msg = str(e)
            if ("429" in err_msg or "ResourceExhausted" in err_msg or "quota" in err_msg.lower()) and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 3
                st.warning(f"⏳ 잠시만요! 사용량이 많아 재시도 중입니다... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise e

# =========================================================
# 📄 PDF 리포트 생성
# =========================================================
def generate_pdf_report(date_str, total_cal, total_carbs, total_protein, total_fat, daily_meals, feedback_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    
    pdf.cell(200, 10, text=f"NutriCare Daily Report ({date_str})", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    pdf.cell(200, 10, text=f"Total: {total_cal} kcal | Carbs: {total_carbs}g | Protein: {total_protein}g | Fat: {total_fat}g", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    pdf.cell(200, 10, text="[ Today's Meals ]", new_x="LMARGIN", new_y="NEXT")
    for m in daily_meals:
        foods_str = ", ".join([f"{f['name']}({f['portion']})" for f in m.get("foods", [])])
        pdf.cell(200, 8, text=f"- [{m.get('meal_type')}] {foods_str} : {m.get('total_calories')} kcal", new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)
    pdf.cell(200, 10, text="[ AI Feedback ]", new_x="LMARGIN", new_y="NEXT")
    
    clean_text = feedback_text.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 8, text=clean_text)
    
    return bytes(pdf.output())

# ---------------------------------------------------------
# 1. 페이지 레이아웃 & MZ 감성 커스텀 CSS 적용
# ---------------------------------------------------------
st.set_page_config(
    page_title="NutriCare",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# 🎨 깔끔한 UI 스타일링 (unsafe_allow_html=True로 정정 완료)
st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    * { font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif; }
    
    .stMetric {
        background-color: #F8FAFC;
        border-radius: 12px;
        padding: 12px 16px;
        border: 1px solid #F1F5F9;
    }
    
    .mz-badge {
        background-color: #EFF6FF;
        color: #2563EB;
        padding: 4px 10px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    </style>
""", unsafe_allow_html=True)

cookie_manager = stx.CookieManager()

if "user" not in st.session_state:
    st.session_state["user"] = None

# ---------------------------------------------------------
# 🍪 쿠키 자동 로그인
# ---------------------------------------------------------
saved_uid = cookie_manager.get(cookie="auth_uid")
saved_email = cookie_manager.get(cookie="auth_email")

if not st.session_state["user"] and saved_uid and saved_email:
    st.session_state["user"] = {"uid": saved_uid, "email": saved_email}

# ---------------------------------------------------------
# 📱 사이드바 설정
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Setting")
    
    user_api_key = st.text_input(
        "🔑 Gemini API Key", 
        type="password",
        placeholder="본인 API 키를 입력하세요"
    )
    
    active_api_key = user_api_key.strip() if user_api_key.strip() else DEFAULT_API_KEY
    
    if user_api_key.strip():
        st.caption("🟢 개인 API 키 사용 중")
    elif DEFAULT_API_KEY:
        st.caption("🔵 기본 API 키 사용 중")
    else:
        st.caption("🔴 API 키를 설정해주세요")

    st.divider()

    target_calories = st.number_input("🎯 하루 목표 칼로리 (kcal)", min_value=1000, max_value=5000, value=2000, step=100)
    
    st.divider()
    
    st.markdown("### 💧 수분 루틴")
    today_str = get_kst_now().strftime("%Y-%m-%d")
    water_key = f"water_{today_str}"
    
    if water_key not in st.session_state:
        st.session_state[water_key] = 0
        
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        if st.button("💧 +250ml", use_container_width=True):
            st.session_state[water_key] += 250
    with col_w2:
        if st.button("🔄 리셋", use_container_width=True):
            st.session_state[water_key] = 0
            
    st.caption(f"오늘 마신 물: **{st.session_state[water_key]} ml** / 2,000 ml")
    st.progress(min(st.session_state[water_key] / 2000.0, 1.0))

    st.divider()
    st.markdown("### 📲 모바일로 이어보기")
    
    try:
        host = st.context.headers.get("host", "")
        current_url = f"https://{host}" if host else "https://share.streamlit.io"
    except Exception:
        current_url = "https://share.streamlit.io"

    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(current_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    
    st.image(buf.getvalue(), caption="QR코드 스캔", width=140)

# ---------------------------------------------------------
# 2. 로그인 / 회원가입 화면
# ---------------------------------------------------------
if not st.session_state["user"]:
    st.markdown("<h1 style='text-align: center;'>🥗 NutriCare</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748B;'>AI가 3초 만에 분석해 주는 내 식단 영양 밸런스</p>", unsafe_allow_html=True)
    st.write("")

    auth_tab1, auth_tab2 = st.tabs(["⚡️ 로그인", "✨ 회원가입"])

    with auth_tab1:
        login_email = st.text_input("이메일", placeholder="example@email.com", key="login_email")
        login_password = st.text_input("비밀번호", type="password", key="login_pwd")
        remember_me = st.checkbox("로그인 유지하기", value=True)
        
        st.write("")
        col_login, col_guest = st.columns(2)
        with col_login:
            if st.button("시작하기", type="primary", use_container_width=True):
                try:
                    user = auth.get_user_by_email(login_email)
                    st.session_state["user"] = {"uid": user.uid, "email": user.email}
                    
                    if remember_me:
                        expires_at = datetime.now() + timedelta(days=30)
                        cookie_manager.set("auth_uid", user.uid, expires_at=expires_at)
                        cookie_manager.set("auth_email", user.email, expires_at=expires_at)
                    
                    st.rerun()
                except Exception:
                    st.error("이메일 또는 비밀번호를 다시 확인해 주세요.")
        
        with col_guest:
            if st.button("👀 둘러보기 (게스트)", use_container_width=True):
                st.session_state["user"] = "guest"
                st.rerun()

    with auth_tab2:
        signup_email = st.text_input("이메일 주소", placeholder="example@email.com", key="signup_email")
        signup_password = st.text_input("비밀번호 (6자리 이상)", type="password", key="signup_pwd")
        st.write("")
        if st.button("가입하고 시작하기", use_container_width=True):
            try:
                user = auth.create_user(email=signup_email, password=signup_password)
                st.success("🎉 가입 완료! 로그인 탭에서 로그인해 주세요.")
            except Exception as e:
                st.error(f"회원가입 실패: {e}")

    st.stop()

# ---------------------------------------------------------
# 3. 메인 서비스 화면
# ---------------------------------------------------------
header_col1, header_col2 = st.columns([3, 1])
with header_col1:
    st.markdown("### 🥗 NutriCare")
    if st.session_state["user"] == "guest":
        st.caption("👀 게스트 로그인 중 (체험 모드)")
    else:
        st.caption(f"👋 {st.session_state['user']['email']}")

with header_col2:
    if st.button("로그아웃", type="secondary", use_container_width=True):
        st.session_state["user"] = None
        cookie_manager.delete("auth_uid")
        cookie_manager.delete("auth_email")
        st.rerun()

st.write("")
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs(["📸 식단 분석", "📂 식단 캘린더", "📊 하루 리포트", "📈 주간 그래프"])

# --- TAB 1: 식단 스캔 ---
with main_tab1:
    sub_tab1, sub_tab2 = st.tabs(["📷 촬영하기", "🖼️ 갤러리"])
    img_file = None

    with sub_tab1:
        camera_photo = st.camera_input("음식을 찍어주세요")
        if camera_photo:
            img_file = camera_photo

    with sub_tab2:
        uploaded_photo = st.file_uploader("사진을 올려주세요", type=["jpg", "jpeg", "png"])
        if uploaded_photo:
            img_file = uploaded_photo

    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="업로드된 사진", use_container_width=True)

        btn_label = "⚡️ AI 식단 스캔 시작" if st.session_state["user"] == "guest" else "⚡️ 식단 스캔 & 기록하기"
        
        if st.button(btn_label, type="primary", use_container_width=True):
            now_kst = get_kst_now()
            current_hour = now_kst.hour
            
            if 5 <= current_hour < 10:
                meal_type = "아침"
            elif 10 <= current_hour < 16:
                meal_type = "점심"
            elif 16 <= current_hour < 22:
                meal_type = "저녁"
            else:
                meal_type = "야식/간식"

            with st.spinner("✨ AI가 칼로리와 영양소를 분석하고 있어요..."):
                try:
                    prompt = f"""
                    당신은 MZ세대 맞춤 친근하고 전문적인 AI 영양 코치입니다.
                    전달받은 사진은 사용자가 **{meal_type}**으로 올린 식단입니다.
                    
                    반드시 아래 예시와 완전히 동일한 Pure JSON 형식으로만 응답해 주세요. 말투는 힙하고 다정하게 부탁합니다.

                    {{
                        "meal_type": "{meal_type}",
                        "total_calories": 550,
                        "carbs_g": 65,
                        "protein_g": 30,
                        "fat_g": 15,
                        "foods": [
                            {{"name": "음식이름", "portion": "1공기", "calories": 300}}
                        ],
                        "health_advice": "한 줄 총평 및 영양 팁"
                    }}
                    """

                    response = generate_content_with_retry(
                        api_key=active_api_key,
                        model_name='gemini-3.6-flash',
                        contents=[prompt, image]
                    )
                    
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

                    st.markdown(f"#### 🏷️ {data['meal_type']} 식단 (총 {data['total_calories']} kcal)")

                    # 지표
                    m1, m2, m3 = st.columns(3)
                    m1.metric("탄수화물", f"{data['carbs_g']} g")
                    m2.metric("단백질", f"{data['protein_g']} g")
                    m3.metric("지방", f"{data['fat_g']} g")

                    st.markdown("---")
                    st.markdown("##### 🍱 감지된 구성")
                    for food in data['foods']:
                        with st.expander(f"📌 **{food['name']}** ({food['portion']})"):
                            st.write(f"예상 칼로리: **{food['calories']} kcal**")

                    st.markdown("##### 💡 코치 한줄평")
                    st.success(data['health_advice'])

                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                        st.error("🚨 사용자가 많아 요청이 제한되었습니다.")
                        st.info("💡 사이드바에 본인 Gemini API 키를 입력하면 대기 없이 사용할 수 있어요!")
                    else:
                        st.error(f"분석 중 오류가 발생했습니다: {e}")

# --- TAB 2: 식단 기록 히스토리 ---
with main_tab2:
    if st.session_state["user"] == "guest":
        st.info("🔒 로그인하면 내 식단 기록이 보관돼요!")
    else:
        meals_ref = db.collection("meals")
        query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).get()

        if not query:
            st.info("아직 기록된 식단이 없어요. 사진을 찍어서 등록해 보세요! 📸")
        else:
            meal_list = [doc.to_dict() for doc in query]
            meal_list.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)

            for item in meal_list:
                with st.expander(f"📅 {item.get('date')} | {item.get('meal_type')} · {item.get('total_calories')} kcal"):
                    st.caption(f"기록 시각: {item.get('time')}")
                    st.write(f"탄수화물 **{item.get('carbs_g')}g** · 단백질 **{item.get('protein_g')}g** · 지방 **{item.get('fat_g')}g**")
                    st.markdown("---")
                    for f in item.get("foods", []):
                        st.write(f"• {f.get('name')} ({f.get('portion')}): {f.get('calories')} kcal")
                    st.caption(f"💬 {item.get('health_advice')}")

# --- TAB 3: 하루 종합 분석 ---
with main_tab3:
    if st.session_state["user"] == "guest":
        st.info("🔒 로그인하면 하루 영양 리포트를 받을 수 있어요!")
    else:
        selected_date = st.date_input("날짜 선택", get_kst_now().date()).strftime("%Y-%m-%d")
        
        meals_ref = db.collection("meals")
        query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).where("date", "==", selected_date).get()
        
        if not query:
            st.warning(f"📅 {selected_date}에 기록된 식단이 없습니다.")
        else:
            daily_meals = [doc.to_dict() for doc in query]
            daily_meals.sort(key=lambda x: x.get("time", ""))
            
            total_cal = sum([m.get("total_calories", 0) for m in daily_meals])
            total_carbs = sum([m.get("carbs_g", 0) for m in daily_meals])
            total_protein = sum([m.get("protein_g", 0) for m in daily_meals])
            total_fat = sum([m.get("fat_g", 0) for m in daily_meals])
            
            progress_ratio = min(total_cal / float(target_calories), 1.0)
            
            if total_cal > target_calories * 1.1:
                st.error(f"⚠️ 목표 대비 초과 달성 중 ({total_cal} / {target_calories} kcal)")
            elif total_cal >= target_calories * 0.8:
                st.success(f"🎉 완전 퍼펙트! 목표 달성 중 ({total_cal} / {target_calories} kcal)")
            else:
                st.info(f"💡 조금 더 채워볼까요? ({total_cal} / {target_calories} kcal)")
                
            st.progress(progress_ratio)
            
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("총 칼로리", f"{total_cal} kcal")
            d2.metric("탄수화물", f"{total_carbs} g")
            d3.metric("단백질", f"{total_protein} g")
            d4.metric("지방", f"{total_fat} g")
            
            st.markdown("---")
            summary_text_list = []
            for m in daily_meals:
                foods_str = ", ".join([f"{f['name']}({f['portion']})" for f in m.get("foods", [])])
                st.write(f"• **[{m.get('meal_type')}]** {foods_str} → `{m.get('total_calories')} kcal`")
                summary_text_list.append(f"- {m.get('meal_type')}: {foods_str} ({m.get('total_calories')}kcal)")
            
            st.write("")
            if st.button("✨ 오늘 하루 AI 영양 피드백 받기", type="primary", use_container_width=True):
                with st.spinner("🤖 AI 영양 코치가 오늘의 식단을 다각도로 분석 중..."):
                    try:
                        daily_summary = "\n".join(summary_text_list)
                        prompt = f"""
                        당신은 친근하고 세련된 2030 영양 전문 코치입니다.
                        오늘 사용자의 식단 데이터:
                        - 총 칼로리: {total_cal} kcal (목표: {target_calories} kcal)
                        - 탄수화물: {total_carbs}g | 단백질: {total_protein}g | 지방: {total_fat}g
                        
                        [상세 기록]
                        {daily_summary}
                        
                        위 데이터를 기반으로 리포트를 작성해 주세요 (1. 칭찬 & 총평, 2. 잘한 점, 3. 아쉬운 점 & 피해야 할 것, 4. 내일 식단 추천). 칭찬 중심의 다정한 톤으로 작성하세요.
                        """
                        
                        response = generate_content_with_retry(
                            api_key=active_api_key,
                            model_name='gemini-3.6-flash',
                            contents=prompt
                        )
                        st.session_state["last_feedback"] = response.text
                        st.markdown("##### 📝 오늘 식단 리포트")
                        st.info(response.text)
                    except Exception as e:
                        st.error(f"리포트 작성 실패: {e}")

            if "last_feedback" in st.session_state:
                pdf_data = generate_pdf_report(selected_date, total_cal, total_carbs, total_protein, total_fat, daily_meals, st.session_state["last_feedback"])
                st.download_button(
                    label="📄 PDF로 간직하기 (다운로드)",
                    data=pdf_data,
                    file_name=f"NutriCare_{selected_date}.pdf",
                    mime="application/pdf"
                )

# --- TAB 4: 주간 차트 ---
with main_tab4:
    if st.session_state["user"] == "guest":
        st.info("🔒 로그인하면 주간 그래프 추이를 볼 수 있어요!")
    else:
        st.markdown("##### 📈 최근 7일 섭취 칼로리")
        
        meals_ref = db.collection("meals")
        query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).get()
        
        if query:
            meal_list = [doc.to_dict() for doc in query]
            
            date_cal_map = {}
            for m in meal_list:
                d = m.get("date", "")
                c = m.get("total_calories", 0)
                date_cal_map[d] = date_cal_map.get(d, 0) + c
                
            sorted_dates = sorted(date_cal_map.keys())[-7:]
            chart_data = {d: date_cal_map[d] for d in sorted_dates}
            
            st.bar_chart(chart_data)
        else:
            st.info("식단을 기록해 주시면 주간 데이터 그래프가 그려집니다!")
