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
from streamlit_option_menu import option_menu
import plotly.graph_objects as go
import plotly.express as px

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
DEFAULT_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

if not firebase_admin._apps:
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 초기화 오류: {e}")

db = firestore.client()

# =========================================================
# 🤖 AI 요청 재시도(Retry) 및 예외 처리 함수
# =========================================================
def generate_content_with_retry(api_key, model_name, contents, max_retries=3):
    if not api_key:
        raise ValueError("API 키가 설정되지 않았습니다. 사이드바에서 Gemini API 키를 입력해 주세요.")
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(contents)
            return response
        except Exception as e:
            err_msg = str(e)
            if ("429" in err_msg or "ResourceExhausted" in err_msg or "quota" in err_msg.lower()) and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 3
                st.warning(f"⏳ 대기 중입니다... ({attempt + 1}/{max_retries} 재시도, {wait_time}초 지연)")
                time.sleep(wait_time)
            else:
                raise e

# =========================================================
# 📄 PDF 리포트 생성 함수
# =========================================================
def generate_pdf_report(date_str, total_cal, total_carbs, total_protein, total_fat, daily_meals, feedback_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    
    pdf.cell(200, 10, text=f"Daily Diet & Nutrition Report ({date_str})", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    pdf.cell(200, 10, text=f"Total Calories: {total_cal} kcal", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(200, 10, text=f"Carbs: {total_carbs}g | Protein: {total_protein}g | Fat: {total_fat}g", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    pdf.cell(200, 10, text="[ Meal Logs ]", new_x="LMARGIN", new_y="NEXT")
    for m in daily_meals:
        foods_str = ", ".join([f"{f['name']}({f['portion']})" for f in m.get("foods", [])])
        pdf.cell(200, 8, text=f"- [{m.get('meal_type')}] {foods_str} : {m.get('total_calories')} kcal", new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)
    pdf.cell(200, 10, text="[ AI Feedback ]", new_x="LMARGIN", new_y="NEXT")
    
    clean_text = feedback_text.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 8, text=clean_text)
    
    return bytes(pdf.output())

# ---------------------------------------------------------
# 1. 페이지 레이아웃 및 프리미엄 CSS
# ---------------------------------------------------------
st.set_page_config(
    page_title="NutriCare Pro - AI 영양 케어 플랫폼",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    
    * {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif !important;
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 4rem;
        max-width: 720px;
    }
    
    /* 카드 컴포넌트 */
    .glass-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
        margin-bottom: 16px;
    }
    
    .metric-box {
        background: #F8FAFC;
        border-radius: 12px;
        padding: 12px;
        text-align: center;
        border: 1px solid #EDF2F7;
    }
    .metric-title {
        font-size: 0.78rem;
        color: #64748B;
        font-weight: 600;
    }
    .metric-value {
        font-size: 1.2rem;
        color: #0F172A;
        font-weight: 700;
        margin-top: 2px;
    }
    
    /* 사용자 지정 태그 */
    .meal-chip {
        display: inline-flex;
        align-items: center;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
        background-color: #EEF2FF;
        color: #4F46E5;
        margin-bottom: 10px;
    }

    /* 버튼 스타일 override */
    div.stButton > button {
        border-radius: 12px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease;
    }
    
    .stProgress > div > div > div > div {
        background-image: linear-gradient(to right, #6366F1 , #3B82F6);
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
    st.markdown("### ⚙️ 설정 & 환경변수")
    
    user_api_key = st.text_input(
        "🔑 개인 Gemini API 키", 
        type="password",
        help="서버 기본 제한을 우회하려면 본인의 API 키를 입력하세요."
    )
    
    active_api_key = user_api_key.strip() if user_api_key.strip() else DEFAULT_API_KEY
    
    if user_api_key.strip():
        st.caption("✅ 개인 API 키 적용 중")
    elif DEFAULT_API_KEY:
        st.caption("ℹ️ 서버 공유 API 키 적용 중")
    else:
        st.warning("⚠️ 등록된 API 키가 없습니다.")

    st.divider()

    target_calories = st.number_input("🎯 하루 목표 칼로리 (kcal)", min_value=1000, max_value=5000, value=2000, step=100)
    
    st.divider()
    
    st.markdown("### 💧 수분 섭취 트래커")
    today_str = get_kst_now().strftime("%Y-%m-%d")
    water_key = f"water_{today_str}"
    
    if water_key not in st.session_state:
        st.session_state[water_key] = 0
        
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        if st.button("➕ 250ml", use_container_width=True):
            st.session_state[water_key] += 250
    with col_w2:
        if st.button("🔄 초기화", use_container_width=True):
            st.session_state[water_key] = 0
            
    st.caption(f"현재: **{st.session_state[water_key]} ml** / 목표 2,000 ml")
    st.progress(min(st.session_state[water_key] / 2000.0, 1.0))

    st.divider()
    st.markdown("### 📱 모바일 접속 QR")
    
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
    
    st.image(buf.getvalue(), caption="카메라로 스캔하여 연결", width=160)

# ---------------------------------------------------------
# 2. 로그인 / 회원가입 / 게스트
# ---------------------------------------------------------
if not st.session_state["user"]:
    st.markdown("""
        <div style='text-align: center; padding: 2rem 0 1rem 0;'>
            <h1 style='font-size: 2.2rem; font-weight: 800; color: #1E293B; margin-bottom: 8px;'>🥗 NutriCare Pro</h1>
            <p style='color: #64748B; font-size: 0.95rem;'>AI 기반 스마트 식단 분석 & 영양 케어 플랫폼</p>
        </div>
    """, unsafe_allow_html=True)

    auth_tab1, auth_tab2 = st.tabs(["🔑 로그인", "📝 회원가입"])

    with auth_tab1:
        login_email = st.text_input("이메일 계정", key="login_email")
        login_password = st.text_input("비밀번호", type="password", key="login_pwd")
        remember_me = st.checkbox("로그인 상태 유지", value=True)
        
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        col_login, col_guest = st.columns(2)
        with col_login:
            if st.button("로그인", type="primary", use_container_width=True):
                try:
                    user = auth.get_user_by_email(login_email)
                    st.session_state["user"] = {"uid": user.uid, "email": user.email}
                    
                    if remember_me:
                        expires_at = datetime.now() + timedelta(days=30)
                        cookie_manager.set("auth_uid", user.uid, expires_at=expires_at)
                        cookie_manager.set("auth_email", user.email, expires_at=expires_at)
                    
                    st.rerun()
                except Exception:
                    st.error("로그인 정보가 올바르지 않습니다.")
        
        with col_guest:
            if st.button("👤 게스트 체험", use_container_width=True):
                st.session_state["user"] = "guest"
                st.rerun()

    with auth_tab2:
        signup_email = st.text_input("이메일 주소", key="signup_email")
        signup_password = st.text_input("비밀번호 (6자리 이상)", type="password", key="signup_pwd")
        if st.button("계정 만들기", use_container_width=True):
            try:
                user = auth.create_user(email=signup_email, password=signup_password)
                st.success("회원가입이 완료되었습니다. 로그인 탭에서 시작하세요.")
            except Exception as e:
                st.error(f"회원가입 실패: {e}")

    st.stop()

# ---------------------------------------------------------
# 3. 메인 Header & 모던 메뉴바 (option_menu 사용)
# ---------------------------------------------------------
h_col1, h_col2 = st.columns([3, 1])
with h_col1:
    st.markdown("<h2 style='margin:0; font-weight:800; color:#0F172A;'>🥗 NutriCare Pro</h2>", unsafe_allow_html=True)
    if st.session_state["user"] == "guest":
        st.caption("⚠️ 게스트 모드 (기록 저장이 제한됩니다)")
    else:
        st.caption(f"👤 {st.session_state['user']['email']}")

with h_col2:
    if st.button("로그아웃", type="secondary", use_container_width=True):
        st.session_state["user"] = None
        cookie_manager.delete("auth_uid")
        cookie_manager.delete("auth_email")
        st.rerun()

# 프리미엄 네비게이션 바
selected_tab = option_menu(
    menu_title=None,
    options=["식단 분석", "식단 기록", "하루 리포트", "주간 추이"],
    icons=["camera", "journal-text", "pie-chart", "graph-up-arrow"],
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {"padding": "0!important", "background-color": "#F8FAFC", "border-radius": "12px", "margin-top": "10px"},
        "icon": {"color": "#64748B", "font-size": "14px"},
        "nav-link": {"font-size": "13px", "text-align": "center", "margin": "0px", "--hover-color": "#F1F5F9", "font-weight": "600"},
        "nav-link-selected": {"background-color": "#4F46E5", "color": "white", "font-weight": "700"},
    }
)

# ---------------------------------------------------------
# TAB 1: 식단 분석
# ---------------------------------------------------------
if selected_tab == "식단 분석":
    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
    sub_tab1, sub_tab2 = st.tabs(["📸 카메라 촬영", "🖼️ 사진 업로드"])
    img_file = None

    with sub_tab1:
        camera_photo = st.camera_input("음식을 촬영하세요")
        if camera_photo:
            img_file = camera_photo

    with sub_tab2:
        uploaded_photo = st.file_uploader("음식 이미지 선택", type=["jpg", "jpeg", "png"])
        if uploaded_photo:
            img_file = uploaded_photo

    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="분석 대상 사진", use_container_width=True)

        btn_label = "🔥 영양 분석 실행" if st.session_state["user"] == "guest" else "🔥 영양 분석 & 자동 저장"
        
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

            with st.spinner("AI가 음식 및 영양 성분을 분석 중입니다..."):
                try:
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

                    # 고급 시각화 카드
                    st.markdown(f"<div class='meal-chip'>{data['meal_type']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<h3 style='margin-bottom:15px;'>총 {data['total_calories']} kcal</h3>", unsafe_allow_html=True)

                    m_col1, m_col2, m_col3 = st.columns(3)
                    with m_col1:
                        st.markdown(f"<div class='metric-box'><div class='metric-title'>탄수화물</div><div class='metric-value'>{data['carbs_g']}g</div></div>", unsafe_allow_html=True)
                    with m_col2:
                        st.markdown(f"<div class='metric-box'><div class='metric-title'>단백질</div><div class='metric-value'>{data['protein_g']}g</div></div>", unsafe_allow_html=True)
                    with m_col3:
                        st.markdown(f"<div class='metric-box'><div class='metric-title'>지방</div><div class='metric-value'>{data['fat_g']}g</div></div>", unsafe_allow_html=True)

                    # Plotly 영양소 파이 차트
                    fig = px.pie(
                        names=['탄수화물', '단백질', '지방'],
                        values=[data['carbs_g']*4, data['protein_g']*4, data['fat_g']*9],
                        hole=0.6,
                        color_discrete_sequence=['#6366F1', '#10B981', '#F59E0B']
                    )
                    fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=220, showlegend=True)
                    st.plotly_chart(fig, use_container_width=True)

                    st.markdown("##### 🍱 세부 구성 항목")
                    for food in data['foods']:
                        with st.expander(f"**{food['name']}** ({food['portion']})"):
                            st.write(f"• 예상 칼로리: **{food['calories']} kcal**")

                    st.markdown("##### 💡 AI 영양 코칭")
                    st.info(data['health_advice'])

                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                        st.error("🚨 사용 요청이 많아 대기 시간이 발생했습니다.")
                        st.info("💡 사이드바에 개인 API 키를 입력하시면 대기 없이 이용할 수 있습니다.")
                    else:
                        st.error(f"분석 오류 발생: {e}")

# ---------------------------------------------------------
# TAB 2: 식단 기록
# ---------------------------------------------------------
elif selected_tab == "식단 기록":
    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
    if st.session_state["user"] == "guest":
        st.info("🔒 게스트 모드에서는 히스토리 기능을 이용할 수 없습니다.")
    else:
        meals_ref = db.collection("meals")
        query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).get()

        if not query:
            st.info("저장된 식단 기록이 없습니다.")
        else:
            meal_list = [doc.to_dict() for doc in query]
            meal_list.sort(key=lambda x: (x.get("date", ""), x.get("time", "")), reverse=True)

            for item in meal_list:
                with st.expander(f"📅 {item.get('date')} | {item.get('meal_type')} ({item.get('total_calories')} kcal)"):
                    st.caption(f"기록 시간: {item.get('time')}")
                    st.write(f"탄수화물 **{item.get('carbs_g')}g** · 단백질 **{item.get('protein_g')}g** · 지방 **{item.get('fat_g')}g**")
                    st.markdown("---")
                    for f in item.get("foods", []):
                        st.write(f"• {f.get('name')} ({f.get('portion')}): {f.get('calories')} kcal")
                    st.caption(f"💬 {item.get('health_advice')}")

# ---------------------------------------------------------
# TAB 3: 하루 리포트
# ---------------------------------------------------------
elif selected_tab == "하루 리포트":
    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
    if st.session_state["user"] == "guest":
        st.info("🔒 게스트 모드에서는 하루 보고서 기능을 이용할 수 없습니다.")
    else:
        selected_date = st.date_input("조회 날짜", get_kst_now().date()).strftime("%Y-%m-%d")
        
        meals_ref = db.collection("meals")
        query = meals_ref.where("uid", "==", st.session_state["user"]["uid"]).where("date", "==", selected_date).get()
        
        if not query:
            st.warning(f"{selected_date}에 기록된 식단이 없습니다.")
        else:
            daily_meals = [doc.to_dict() for doc in query]
            daily_meals.sort(key=lambda x: x.get("time", ""))
            
            total_cal = sum([m.get("total_calories", 0) for m in daily_meals])
            total_carbs = sum([m.get("carbs_g", 0) for m in daily_meals])
            total_protein = sum([m.get("protein_g", 0) for m in daily_meals])
            total_fat = sum([m.get("fat_g", 0) for m in daily_meals])
            
            # Plotly 게이지 차트
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_cal,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "일일 섭취 칼로리 달성률", 'font': {'size': 14}},
                gauge={
                    'axis': {'range': [None, target_calories * 1.2]},
                    'bar': {'color': "#4F46E5"},
                    'steps': [
                        {'range': [0, target_calories * 0.8], 'color': "#E0E7FF"},
                        {'range': [target_calories * 0.8, target_calories * 1.1], 'color': "#C7D2FE"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': target_calories
                    }
                }
            ))
            fig_gauge.update_layout(height=220, margin=dict(t=30, b=10, l=30, r=30))
            st.plotly_chart(fig_gauge, use_container_width=True)

            d_col1, d_col2, d_col3, d_col4 = st.columns(4)
            with d_col1:
                st.markdown(f"<div class='metric-box'><div class='metric-title'>총 칼로리</div><div class='metric-value'>{total_cal}</div></div>", unsafe_allow_html=True)
            with d_col2:
                st.markdown(f"<div class='metric-box'><div class='metric-title'>탄수화물</div><div class='metric-value'>{total_carbs}g</div></div>", unsafe_allow_html=True)
            with d_col3:
                st.markdown(f"<div class='metric-box'><div class='metric-title'>단백질</div><div class='metric-value'>{total_protein}g</div></div>", unsafe_allow_html=True)
            with d_col4:
                st.markdown(f"<div class='metric-box'><div class='metric-title'>지방</div><div class='metric-value'>{total_fat}g</div></div>", unsafe_allow_html=True)
            
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
            summary_text_list = []
            for m in daily_meals:
                foods_str = ", ".join([f"{f['name']}({f['portion']})" for f in m.get("foods", [])])
                st.write(f"• **[{m.get('meal_type')}]** {foods_str} → `{m.get('total_calories')} kcal`")
                summary_text_list.append(f"- {m.get('meal_type')}: {foods_str} ({m.get('total_calories')}kcal)")
            
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            
            if st.button("🤖 AI 종합 영양 리포트 생성", type="primary", use_container_width=True):
                with st.spinner("종합 영양 상태 평가를 작성 중입니다..."):
                    try:
                        daily_summary = "\n".join(summary_text_list)
                        prompt = f"""
                        당신은 수석 영양 코치입니다. 사용자의 오늘 하루 식단 데이터:
                        - 총 칼로리: {total_cal} kcal (목표: {target_calories} kcal)
                        - 탄수화물: {total_carbs}g | 단백질: {total_protein}g | 지방: {total_fat}g
                        
                        [세부 기록]
                        {daily_summary}
                        
                        위 데이터를 바탕으로 종합 평가 보고서를 작성해 주세요 (1. 종합 평가, 2. 잘한 점, 3. 개선 가이드, 4. 내일 식단 팁).
                        """
                        
                        response = generate_content_with_retry(
                            api_key=active_api_key,
                            model_name='gemini-3.6-flash',
                            contents=prompt
                        )
                        st.session_state["last_feedback"] = response.text
                        st.markdown("##### 📋 일일 영양 리포트 결과")
                        st.info(response.text)
                    except Exception as e:
                        st.error(f"보고서 생성 실패: {e}")

            if "last_feedback" in st.session_state:
                pdf_data = generate_pdf_report(selected_date, total_cal, total_carbs, total_protein, total_fat, daily_meals, st.session_state["last_feedback"])
                st.download_button(
                    label="📄 PDF 리포트 다운로드",
                    data=pdf_data,
                    file_name=f"nutricare_report_{selected_date}.pdf",
                    mime="application/pdf"
                )

# ---------------------------------------------------------
# TAB 4: 주간 추이
# ---------------------------------------------------------
elif selected_tab == "주간 추이":
    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
    if st.session_state["user"] == "guest":
        st.info("🔒 게스트 모드에서는 추이 시각화 기능을 이용할 수 없습니다.")
    else:
        st.markdown("##### 📈 최근 7일 섭취 트렌드")
        
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
            c_values = [date_cal_map[d] for d in sorted_dates]
            
            # Plotly Line/Area 막대 차트
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=sorted_dates,
                y=c_values,
                marker_color='#6366F1',
                name='섭취 칼로리'
            ))
            fig_bar.add_hline(y=target_calories, line_dash="dash", line_color="red", annotation_text="목표 칼로리")
            fig_bar.update_layout(
                xaxis_title="날짜",
                yaxis_title="kcal",
                height=320,
                margin=dict(t=20, b=20, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("저장된 일별 데이터가 부족합니다.")
