import os, json, time, datetime, requests, unicodedata
from typing import Dict, Any, List, Tuple

RR_BASE = "https://runrun.it/api/v1.0"
APP_KEY = os.environ["RUNRUN_APP_KEY"]
USER_TOKEN = os.environ["RUNRUN_USER_TOKEN"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
DEFAULT_CAPACITY_SECONDS = int(os.getenv("DEFAULT_CAPACITY_SECONDS", "28800"))
THRESHOLD = float(os.getenv("THRESHOLD", "1.0"))
ONLY_TEAM_IDS = [int(x) for x in os.getenv("ONLY_TEAM_IDS", "").split(",") if x.strip()]
EXCLUDE_USER_IDS = {x.strip() for x in os.getenv("EXCLUDE_USER_IDS", "").split(",") if x.strip()}
INCLUDE_WEEKENDS = os.getenv("INCLUDE_WEEKENDS", "false").lower() == "true"
LOCAL_TZ = os.getenv("LOCAL_TZ", "America/Fortaleza")

HEADERS = {"App-Key": APP_KEY, "User-Token": USER_TOKEN, "Content-Type": "application/json"}
TELEGRAM_LIMIT = 4096  # limite de caracteres do Telegram

# --- Normalização para comparar nomes sem acento/caixa ---
def _norm(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).strip().lower()

# --- Exclusões fixas por NOME (não entram na análise) ---
EXCLUDE_USER_NAMES = [
    "Lucas Marques",
    "Ana Martha Vazquez",
    "Bruno Montenegro",
    "Daniel Costa",
    "Fábio Assunção",
    "Franklin Passos",
    "Júlia Trindade",
    "Lais Melo",
    "Samara Amorim",
    "Silvânia Bertulina",
    "Wilian Nakamura",
    "Barbara Fraga",
    "Lívia Souza",
]
EXCLUDE_USER_NAMES_NORM = {_norm(n) for n in EXCLUDE_USER_NAMES}

# --- HTTP helpers com retry ---
def http_get_resp(url: str, headers: Dict[str, str], params: Dict[str, Any] = None, retries: int = 3, timeout: int = 25) -> requests.Response:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code >= 400:
                raise Exception(f"HTTP {r.status_code}: {r.text}")
            return r
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)

# --- Runrun.it helpers ---
def rr_get(path: str, params: Dict[str, Any] = None) -> Any:
    r = http_get_resp(f"{RR_BASE}{path}", HEADERS, params=params)
    return r.json()

# Paginação geral baseada no header Link/X-Item-Range (page/limit)
# Docs indicam uso de page/limit/offset e header Link (rel="next").
# Agrega os campos de interesse (result/capacity) ao longo das páginas.

def rr_get_paginated_time_worked(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    page = 1
    limit = 100
    all_result: List[Dict[str, Any]] = []
    all_capacity: List[Dict[str, Any]] = []
    while True:
        p = dict(params)
        p.update({"page": page, "limit": limit})
        resp = http_get_resp(f"{RR_BASE}{path}", HEADERS, params=p)
        data = resp.json()
        if isinstance(data, dict):
            all_result.extend(data.get("result", []) or [])
            cap = data.get("capacity", []) or []
            if cap:
                all_capacity.extend(cap)
        link = resp.headers.get("Link", "")
        if 'rel="next"' not in link:
            break
        page += 1
    return {"result": all_result, "capacity": all_capacity}

# --- Runrun: usuários/times ---
def list_users() -> List[Dict[str, Any]]:
    data = rr_get("/users")
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data

def list_teams() -> List[Dict[str, Any]]:
    data = rr_get("/teams")
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data

# --- Relatório Time Worked (com paginação) ---
def get_time_worked_today() -> Dict[str, Tuple[int, int]]:
    today = datetime.datetime.now(datetime.timezone.utc).astimezone().date().isoformat()
    params = {
        "group_by": "user_id,date",
        "period_type": "custom_range",
        "period_start": today,
        "period_end": today,
        "period_unit": "day",
        "include_capacity": "true",
    }
    data = rr_get_paginated_time_worked("/reports/time_worked", params)

    result = data.get("result", [])
    capacity_list = data.get("capacity", [])

    worked_by_user: Dict[str, int] = {}
    for row in result:
        uid = row.get("user_id") or row.get("user", {}).get("id")
        if not uid:
            continue
        t = int(row.get("time", 0))
        worked_by_user[str(uid)] = worked_by_user.get(str(uid), 0) + t

    cap_by_user: Dict[str, int] = {}
    for c in capacity_list:
        uid = c.get("user_id") or c.get("user", {}).get("id")
        if uid:
            cap_by_user[str(uid)] = int(c.get("time", 0))
    if not cap_by_user:
        for uid in worked_by_user:
            cap_by_user[uid] = DEFAULT_CAPACITY_SECONDS

    all_ids = set(list(worked_by_user.keys()) + list(cap_by_user.keys()))
    return {uid: (worked_by_user.get(uid, 0), cap_by_user.get(uid, DEFAULT_CAPACITY_SECONDS)) for uid in all_ids}

# --- Mapa de menções de líderes por COLABORADOR ---
LEADER_HANDLES: Dict[str, List[str]] = {
    "Lara Silveira": ["@SilvaniaAuditoria"],
    "João Gouveia": ["@SilvaniaAuditoria"],
    "Juan Lucas": ["@SilvaniaAuditoria"],
    "Luiza Correia": ["@SilvaniaAuditoria"],
    "Nicolas Miranda": ["@SilvaniaAuditoria"],
    "Pedro Vidal": ["@SilvaniaAuditoria"],
    "Alexandre Andrade": ["@NakamuraAuditoria"],
    "Caio Vilamaior": ["@NakamuraAuditoria"],
    "Israel Brito": ["@NakamuraAuditoria"],
    "Matheus Eufrásio": ["@NakamuraAuditoria"],
    "Raul Costa": ["@NakamuraAuditoria"],
    "Wether Rios": ["@NakamuraAuditoria"],
    "Yuri Peixoto": ["@NakamuraAuditoria"],
    "Ana Clara Gois": ["@FranklinAuditoria"],
    "Cauã Amorim": ["@FranklinAuditoria"],
    "Elissandra Alexandre": ["@FranklinAuditoria"],
    "Lara Farias": ["@FranklinAuditoria"],
    "Sophie Viana": ["@FranklinAuditoria"],
    "Yara Esteves": ["@FranklinAuditoria"],
    "Yasmin Barros": ["@FranklinAuditoria"],
    "Bruno Rocha": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Lucas Marques": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Marcos Morais": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Sylvia Meyer": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Amadeu Henrique": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Carlos Silva": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Judite Sombra": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Rafael Fontenelle": ["@LaisAuditoria", "@SamaraAuditoria"],
    "Victor Teles": ["@JuliaAuditoria"],
    "Vinícius Campos": ["@JuliaAuditoria"],
    "Gustavo dos Santos": ["@JuliaAuditoria"],
    "Julie Santander": ["@JuliaAuditoria"],
    "Kaio de Oliveira": ["@JuliaAuditoria"],
    "Nicole Vasconcelos": ["@JuliaAuditoria"],
    "Vivian Rodrigues": ["@JuliaAuditoria"],
    "Ana Martha Vazquez": ["@BrunoAuditoria"],
    "Bruno Montenegro": ["@BrunoAuditoria"],
    "Daniel Costa": ["@BrunoAuditoria"],
    "Fábio Assunção": ["@BrunoAuditoria"],
    "Franklin Passos": ["@BrunoAuditoria"],
    "Júlia Trindade": ["@BrunoAuditoria"],
    "Lais Melo": ["@BrunoAuditoria"],
    "Samara Amorim": ["@BrunoAuditoria"],
    "Silvânia Bertulina": ["@BrunoAuditoria"],
    "Wilian Nakamura": ["@BrunoAuditoria"],
    "Barbara Fraga": ["@FabioAuditoria"],
    "Caio Chandler": ["@FabioAuditoria"],
    "Emanuel Guimarães": ["@FabioAuditoria"],
    "Valmir Soares": ["@FabioAuditoria"],
    "Guilherme Alencar": ["@FabioAuditoria"],
    "Jose Vitor": ["@FabioAuditoria"],
    "Lorenzo Silva": ["@FabioAuditoria"],
    "Manoel Victor": ["@FabioAuditoria"],
    "Thiago Beserra": ["@FabioAuditoria"],
    "Thiago Pereira": ["@FabioAuditoria"],
    "Joyce Rolim": ["@DanielAuditoria"],
    "Emilly Souza": ["@DanielAuditoria"],
    "Maria Clara Assunção": ["@DanielAuditoria"],
    "Rafael Soares": ["@DanielAuditoria"],
    "Remulo Wesley": ["@DanielAuditoria"],
    "Rene Filho": ["@DanielAuditoria"],
    "Carlos Heitor": ["@AnaAuditoria"],
    "Flavio Sousa": ["@AnaAuditoria"],
    "Fernanda Rabello": ["@AnaAuditoria"],
    "Glailson Oliveira": ["@AnaAuditoria"],
    "Joao Vitor": ["@AnaAuditoria"],
    "Maicon Monteiro": ["@AnaAuditoria"],
    "Sthefany Araújo": ["@AnaAuditoria"],
    "Igor Benevides": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Lívia Souza": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Ana Rosa Freitas": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Bruna Lima": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Clara Gurgel": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Lilian Alves": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Thalita Gomes": ["@SamaraAuditoria", "@LaisAuditoria"],
    "Yasmin Queiroz": ["@SamaraAuditoria", "@LaisAuditoria"],
    "João Victor Fortes": ["@DanielAuditoria"],
    "Ana Clara Aragão": ["@SilvaniaAuditoria"],
}

# --- Telegram: split seguro ---

def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> List[str]:
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("
", 0, limit)
        if cut == -1:
            cut = remaining.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return parts


def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in split_message(text):
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=25)
        if r.status_code >= 400:
            raise Exception(f"Telegram {r.status_code}: {r.text}")

# --- Main ---

def main():
    if not INCLUDE_WEEKENDS and datetime.datetime.now().weekday() >= 5:
        return

    users = list_users()
    teams = list_teams()  # ainda útil para filtros por time

    # Mapa id->usuário e remoção por nome (exclusões)
    users_by_id = {str(u.get("id")): u for u in users}
    users_by_id = {k: v for k, v in users_by_id.items() if _norm(v.get("name", "")) not in EXCLUDE_USER_NAMES_NORM}

    if ONLY_TEAM_IDS:
        keep = set()
        for team in teams:
            if int(team.get("id", -1)) in ONLY_TEAM_IDS:
                for uid in team.get("user_ids", []):
                    keep.add(str(uid))
        users_by_id = {k: v for k, v in users_by_id.items() if k in keep}

    for x in list(users_by_id.keys()):
        if str(x) in EXCLUDE_USER_IDS:
            users_by_id.pop(x, None)

    worked_today = get_time_worked_today()

    for uid, (worked, capacity) in worked_today.items():
        if uid not in users_by_id:
            continue
        if capacity <= 0:
            continue
        if worked >= capacity * THRESHOLD:
            user = users_by_id.get(uid, {})
            u_name = user.get("name", uid)
            hours = worked / 3600.0
            cap_h = capacity / 3600.0

            leaders = LEADER_HANDLES.get(u_name, [])
            leader_text = " ".join(leaders) if leaders else "(líder não mapeado)"

            txt_lines = [
                "Alerta: 100% do tempo trabalhado atingido",
                f"Colaborador: {u_name}",
                f"Trabalhado hoje: {hours:.2f}h de {cap_h:.2f}h",
                f"Líder: {leader_text}",
            ]
            txt = "
".join(txt_lines)
            tg_send(txt)

if __name__ == "__main__":
    main()
