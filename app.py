import os
import io
import json
from datetime import datetime
import streamlit as st
import qrcode
from PIL import Image
import google.generativeai as genai

# =========================================================
# 🔑 API KEY 설정 (Streamlit Secrets 지원)
# =========================================================
API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

# ---------------------------------------------------------
# 1. 페이지 레이아웃
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI 식단 분석 코치",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# 2. 메인 UI 화면 구성
# ---------------------------------------------------------
st.title("🥗 AI 식단 분석 코치")
st.caption("스마트폰 카메라로 사진을 찍거나 업로드하면 AI가 실시간 영양성분을 분석합니다.")

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

# 카메라 촬영 / 앨범 업로드
tab1, tab2 = st.tabs(["📸 카메라 촬영", "🖼️ 앨범에서 선택"])
img_file = None

with tab1:
    camera_photo = st.camera_input("음식을 촬영하세요")
    if camera_photo:
        img_file = camera_photo

with tab2:
    uploaded_photo = st.file_uploader("음식 이미지 파일 선택", type=["jpg", "jpeg", "png"])
    if uploaded_photo:
        img_file = uploaded_photo

# 사진 입력 시 분석 진행
if img_file:
    image = Image.open(img_file)
    st.image(image, caption="분석 대상 이미지", use_container_width=True)

    if not API_KEY or API_KEY == "여기에_Gemini_API_KEY_입력":
        st.error("⚠️ Streamlit Secrets에 GEMINI_API_KEY를 등록해 주세요.")
    else:
        if st.button("🔥 AI 영양 분석 실행", type="primary", use_container_width=True):
            # 1. 시간대별 식사 구분 자동 계산
            current_hour = datetime.now().hour
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
                    # Gemini 설정 및 빠른 모델(gemini-2.5-flash) 적용
                    genai.configure(api_key=API_KEY)
                    model = genai.GenerativeModel('gemini-2.5-flash')

                    # 2. JSON 형태 결과 응답을 위한 맞춤 프롬프트
                    prompt = f"""
                    당신은 전문 영양 코치입니다. 전달받은 이미지는 사용자가 **{meal_type}**으로 제출한 식단 사진입니다.
                    
                    반드시 아래 예시와 완전히 똑같은 형태의 Pure JSON 형식으로만 응답해 주세요. (Markdown ```json 태그나 다른 설명 금지)

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
                    
                    # 3. JSON 파싱
                    clean_text = response.text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean_text)

                    # 4. 분석 결과 화면 표시
                    st.success("분석 완료!")
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
