import os
import io
import streamlit as st
import qrcode
from PIL import Image
import google.generativeai as genai

# =========================================================
# 🔑 API KEY 직접 설정 (본인의 API Key를 입력하세요)
# =========================================================
# ❌ 기존: API_KEY = "AIzaSy..."
# ⭕ 수정: Streamlit 보안 설정(Secrets)에서 키를 불러오는 방식
API_KEY = st.secrets.get("GEMINI_API_KEY", "")

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
        st.error("⚠️ app.py 파일 상단의 API_KEY 변수에 본인의 Gemini API Key를 입력해주세요.")
    else:
        if st.button("🔥 AI 영양 분석 실행", type="primary", use_container_width=True):
            with st.spinner("AI가 식단을 분석 중입니다..."):
                try:
                    # Gemini 설정
                    genai.configure(api_key=API_KEY)
                    model = genai.GenerativeModel('gemini-3.6-flash')

                    prompt = """
                    이 음식 사진을 분석해서 아래 JSON 양식으로만 답변해줘. 마크다운 기호 없이 순수 JSON만 출력해.
                    {
                      "meal_type": "식사 종류 (예: 점심 식단)",
                      "total_calories": 총 칼로리 숫자,
                      "carbs_g": 총 탄수화물g 숫자,
                      "protein_g": 총 단백질g 숫자,
                      "fat_g": 총 지방g 숫자,
                      "foods": [
                        {"name": "음식명", "portion": "양", "calories": 칼로리숫자}
                      ],
                      "health_advice": "영양학적 조언 2~3문장"
                    }
                    """

                    response = model.generate_content([prompt, image])
                    
                    # JSON 파싱
                    import json
                    clean_text = response.text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean_text)

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
                    
# 1. 터미널 열기
# VS Code 실행 후 단축키 Ctrl + Shift + ' (또는 상단 메뉴 Terminal -> New Terminal)를 눌러 터미널을 엽니다.

# 2. 한 번에 한 줄로 명령어 입력하기
# 터미널에 아래 명령어를 그대로 복사해서 붙여넣고 Enter를 칩니다.
# PowerShell
# python -m pip install streamlit google-genai pillow pydantic qrcode[pil]
# 설치되는 핵심 패키지 항목
# streamlit: 웹 UI 화면을 띄워주는 프레임워크
# google-genai: Gemini 3.6 모델을 호출하는 구글 공식 SDK
# pillow: 사진(이미지) 업로드 및 처리를 위한 라이브러리
# pydantic & qrcode[pil]: 영양 데이터 구조화 및 QR 코드 생성용 패키지

# 3. 학교 컴퓨터 실행 팁
# 학교 컴퓨터는 재부팅하면 설치했던 라이브러리가 싹 삭제(원복)되는 경우가 많습니다.
# 따라서 학교에서 수업이나 발표 시작 직전에 위 pip install 명령어 한 줄을 터미널에 먼저 쳐서 라이브러리를 깔아준 뒤, python -m streamlit run app.py를 실행하시면 깔끔하게 작동합니다.
# VS Code 왼쪽 파일 목록(Explorer)에 있는 app.py 우클릭 ➔ [Copy Path] (경로 복사)를 누른 뒤, 터미널에 아래처럼 따옴표 안에 붙여넣고 엔터를 누르세요!

# PowerShell
# python -m streamlit run "복사한경로붙여넣기"
