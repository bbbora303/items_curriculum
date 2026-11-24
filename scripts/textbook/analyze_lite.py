"""쪽 분석 요청을 만든다 (일반 실행 analyze_book.py와 배치 실행 analyze_batch.py가 같이 쓴다).

프로필:
- full : 모든 항목(문제 목록, 그림 목록, 성질·예제 등)을 정밀하게 기록한다. 쪽당 출력 약 1.4천 토큰.
- lite : 이후 단계(종합·범위·문체·전사 대상 선정)가 **실제로 쓰는 항목만** 기록한다. 출력이 약 1/3~1/4로 줄어든다.
         용어(정의/사용), 단원, 쪽 유형, 학년 연결, 발문 지시어, 소재, 서술형 문제 유무, 값이 필요한 표·그래프 유무.
         문제 요약·그림 목록·성질·예제는 기록하지 않는다(필요한 쪽만 transcribe_pages.py로 원문 전사).
이미지 폭(width)을 줄이면 입력 토큰이 줄지만 작은 글자·수식을 못 읽을 수 있다(1100 → 900은 약 30% 절감 추정, 읽기 품질은 시험 필요).
"""
LITE_SYSTEM = """당신은 한국 중학교 수학 교과서를 분석하는 도우미입니다. 한 쪽의 이미지(기준)와 PDF 글자층(보조, 수식 기호가 깨져 있음)을 받아 아래 JSON 한 개만 출력합니다. 설명 문장·코드 블록 표시는 쓰지 않습니다.
원칙:
- 이미지에 실제로 보이는 것만 적는다. 추측하지 않는다. 불확실하면 notes에 짧게 적는다.
- 수식은 LaTeX($...$, JSON 문자열 안에서 역슬래시는 두 번: \\\\frac). 글자층의 깨진 기호는 무시하고 이미지를 따른다.
- 학년 판별이 목적이다: 이 쪽에서 새로 정의·도입되는 용어(role=정의, definition은 교과서 정의를 한 문장으로)와, 이미 배웠다고 전제하고 쓰는 용어(role=사용)를 구별한다. 단원 도입 쪽의 '배운 내용 / 이 단원의 내용 / 배울 내용(중2·중3 표시)'은 gradeLinks에 옮긴다.
- 쪽 위·아래의 단원 표시와 소단원 번호·제목이 보이면 unit에 적고, 보이지 않으면 빈 문자열.
- 문제·예제·그림의 내용은 기록하지 않는다. 아래 네 가지만 센다/표시한다: 발문 끝 반응 지시어(verbs, 예: 구하시오), 실생활 소재(contexts, 최대 6개), 서술형 문제 표시가 있는 문제가 있는지(essay), 표나 그래프가 문제·개념의 자료로 쓰였는지(dataFigures, 장식은 제외).
출력 JSON 형식(모든 키를 쓰고 해당 없으면 빈 배열/빈 문자열/false/0):
{"printedPage":"쪽 아래 인쇄된 쪽 번호","unit":{"chapter":"대단원 이름","section":"소단원 번호와 제목","area":"교재 코너명"},
 "pageType":"표지|차례|단원도입|개념설명|예제|연습문제|탐구활동|읽기자료|서술형문제|단원마무리|자기평가|부록|기타 중 하나",
 "terms":[{"term":"용어","role":"정의|사용","definition":"정의를 한 문장으로(role=정의일 때)","notation":"기호가 있으면 LaTeX"}],
 "gradeLinks":{"prior":["배운 내용"],"current":["이 단원의 내용"],"later":[{"item":"배울 내용","grade":"중2|중3|고"}]},
 "verbs":["발문 끝 반응 지시어(중복 없이)"],"contexts":["실생활 소재"],"essay":false,"dataFigures":false,"problemCount":0,
 "notes":"불확실한 부분(없으면 빈 문자열)"}"""

MAX_TOKENS = {"full": 12000, "lite": 4000}


def build_request(analyze_book, doc, i, units, profile="full", width=1100):
    """한 쪽의 분석 요청(system, content, max_tokens)을 만든다."""
    b64, text = analyze_book.render(doc, i, width)
    system = analyze_book.SYSTEM if profile == "full" else LITE_SYSTEM
    user_text = (f"이 교과서의 대단원 목록: {units}\nPDF 쪽 순서 {i + 1}번째 쪽입니다.\n"
                 f"[글자층(보조, 수식 깨짐)]\n{text[:6000]}\n\n위 이미지를 분석해 JSON을 출력하세요.")
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}, {"type": "text", "text": user_text}]
    return {"system": system, "content": content, "max_tokens": MAX_TOKENS[profile], "user_text": user_text}
