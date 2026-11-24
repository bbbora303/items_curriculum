"""교과서 쪽 분석의 `kind` 값을 목적별 이름과 정리된 값으로 바꾼다 (규칙 기반, API 호출 없음).

원래 AI가 붙인 `kind`는 4가지 뜻으로 섞여 있었다. 이름을 나누고, 애매한 값('방법', '기타', '그림')을 규칙으로 가른다.
- statements[].kind  -> statementType   (정의 / 성질 / 공식 / 법칙 / 계산·풀이 방법 / 도구 활용 / 활동 안내)
- examples[].kind    -> exampleType     (계산 / 식세우기 / 판단 / 그리기 / 설명 / 개념 예시 / 활동 예시)
- problems[].kind    -> problemType     (계산 / 식세우기 / 판단 / 그리기 / 설명 / 탐구 / 표현하기 / 채우기·고르기·나열 / 정답·해설 / 기타)
- figures[].kind     -> figureType      (도형 / 표 / 그래프 / 좌표평면 / 수직선 / 모형 / 수학 다이어그램 / 공학도구 화면 / 사진 / 삽화 / QR코드 / 기타)
원래 값은 `_raw` 키에 남긴다(되돌릴 수 있게). normalize_page()는 여러 번 해도 결과가 같다.
"""
import re

STATEMENT = ["정의", "성질", "공식", "법칙", "계산·풀이 방법", "도구 활용", "활동 안내"]
EXAMPLE = ["계산", "식세우기", "판단", "그리기", "설명", "개념 예시", "활동 예시"]
PROBLEM = ["계산", "식세우기", "판단", "그리기", "설명", "탐구", "표현하기", "채우기·고르기·나열", "정답·해설", "기타"]
FIGURE = ["도형", "표", "그래프", "좌표평면", "수직선", "모형", "수학 다이어그램", "공학도구 화면", "사진", "삽화", "QR코드", "기타"]

TOOL = re.compile(r"알지오매스|공학 ?도구|입력 ?창|프로그램|스프레드시트|엑셀|코딩|블록|QR")
ACTIVITY = re.compile(r"놀이|빙고|게임|발표|토의|모둠|친구와|만들어 보|그려 보|써 보|조사|카드 뉴스|포스터|캐릭터|시를|활동")


def statement_type(s):
    k = s.get("kind")
    if k == "정리":                      # 정리(theorem)는 성질로 합친다
        return "성질"
    if k in ("정의", "성질", "공식", "법칙"):
        return k
    txt = f"{s.get('latex', '')} {s.get('plain', '')}"
    if TOOL.search(txt):
        return "도구 활용"
    if ACTIVITY.search(txt) and not re.search(r"계산|구한다|구하|곱|나눈|더한|뺀|그래프", txt):
        return "활동 안내"
    return "계산·풀이 방법"


def example_type(e, page_type):
    k = e.get("kind")
    if k in ("계산", "식세우기", "판단", "그리기", "설명"):
        return k
    return "활동 예시" if page_type in ("탐구활동", "읽기자료") else "개념 예시"


def problem_type(p, page_type):
    k = p.get("kind")
    verb, summ, label = (p.get("verb") or "").strip(), p.get("summary") or "", str(p.get("label") or "").strip()
    answer_like = verb == "답" or summ.startswith("답") or "정답" in summ
    if page_type in ("부록", "기타") and (not label or answer_like):
        return "정답·해설"
    if k in ("계산", "식세우기", "판단", "그리기", "설명", "탐구"):
        return k
    if answer_like:
        return "정답·해설"
    if re.search(r"나타내|표현|기호로", verb + summ):
        return "표현하기"
    if re.search(r"채우|써넣|나열|맞추|찾|고르|분류|연결|골라|짝", verb + summ):
        return "채우기·고르기·나열"
    if re.search(r"풀|계산|구하", verb + summ):
        return "계산"
    return "기타"


SCREEN = re.compile(r"알지오매스|이지통계|통계 프로그램|기하 ?창|입력 ?창|블록 코딩|캡처|프로그램 화면")
ILLUST = re.compile(r"삽화|일러스트|캐릭터|만화|캐리커처|풍경|인물 그림|초상")
GEOM = re.compile(r"직선|반직선|선분|평행|각도|∠|맞꼭지|동위각|엇각|삼각형|사각형|원뿔|원기둥|기둥|뿔|구의|회전체|다면체|전개도|길이가 표시|도형|꼭짓점|작도")
DIAGRAM = re.compile(r"벤|가지|나무|배열|흐름|화살표|도식|다이어그램|카드|룰렛|과정|상자|분류|요약")


def figure_type(g):
    k = g.get("kind")
    desc, role = g.get("desc", ""), g.get("role", "")
    if re.search(r"QR", desc):
        return "QR코드"
    if SCREEN.search(desc):
        return "공학도구 화면"
    if k in ("도형", "표", "그래프", "좌표평면", "수직선", "모형", "사진"):
        return k
    if ILLUST.search(desc) or (role == "장식" and not DIAGRAM.search(desc)):
        return "삽화"
    if GEOM.search(desc) and role != "장식":
        return "도형"
    if DIAGRAM.search(desc):
        return "수학 다이어그램"
    return "기타"


NOTES_NUM = re.compile(r"(이 된다|이다\.|이므로|따라서|합은|정답은|값은|계산하면|=)")


def quality_flags(d):
    """값은 바꾸지 않고 의심 표시만 붙인다(멱등).
    - _notesInferred: notes에 숫자 계산·결론이 있다 → AI가 덧붙인 추론일 수 있어 사실 자료로 쓰지 않는다(예: 17쪽 공약수 계산 오류).
    - 문제의 _levelSuspect: 연습문제·단원마무리 쪽에서 번호가 숫자뿐인 문제가 level '활동'으로 분류됨 → 일반 문제일 수 있다(활동 쪽의 번호 활동은 정상이라 값은 바꾸지 않는다)."""
    notes = d.get("notes") or ""
    d["_notesInferred"] = bool(NOTES_NUM.search(notes) and re.search(r"\d", notes))
    area = (d.get("unit") or {}).get("area", "")
    if d.get("pageType") in ("연습문제", "단원마무리") and "활동" not in area:
        for p in d.get("problems", []):
            if p.get("level") == "활동" and re.fullmatch(r"\d+\+?", str(p.get("label", "")).strip()):
                p["_levelSuspect"] = True
    return d


def normalize_page(d):
    """쪽 하나(dict)를 제자리에서 정리한다. 이미 정리된 쪽은 그대로 둔다."""
    quality_flags(d)
    pt = d.get("pageType", "")
    for s in d.get("statements", []):
        if "kind" in s:
            s["_raw"] = s.pop("kind")
            s["statementType"] = statement_type({**s, "kind": s["_raw"]})
    for e in d.get("examples", []):
        if "kind" in e:
            e["_raw"] = e.pop("kind")
            e["exampleType"] = example_type({**e, "kind": e["_raw"]}, pt)
    for p in d.get("problems", []):
        if "kind" in p:
            p["_raw"] = p.pop("kind")
            p["problemType"] = problem_type({**p, "kind": p["_raw"]}, pt)
    for g in d.get("figures", []):
        if "kind" in g:
            g["_raw"] = g.pop("kind")
            g["figureType"] = figure_type({**g, "kind": g["_raw"]})
    return d
