import os
import random
from datetime import datetime, timezone, timedelta
import pandas as pd
from sqlalchemy import create_engine, text


DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)


def get_templates() -> pd.DataFrame:
    """Вернуть все активные шаблоны писем."""
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM templates WHERE is_active = TRUE ORDER BY id", conn)
    return df


def get_clients() -> pd.DataFrame:
    """Вернуть всех клиентов."""
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM clients ORDER BY id", conn)
    return df


def create_campaign(name: str, template_id: int, description: str = "") -> int:
    """Создать кампанию и вернуть её id."""
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO campaigns (name, template_id, description, status, created_at, planned_at)
        VALUES (:name, :template_id, :description, :status, :created_at, :planned_at)
        RETURNING id
    """)

    with engine.begin() as conn:  # begin = автокоммит транзакции
        result = conn.execute(
            sql,
            {
                "name": name,
                "template_id": template_id,
                "description": description,
                "status": "FINISHED",  # для простоты считаем сразу завершённой
                "created_at": now,
                "planned_at": now,
            },
        )
        campaign_id = result.scalar_one()

    return campaign_id


def _simulate_status(sent_at: datetime):
    """
    Имитация статуса письма и времена opened/clicked.

    Пропорции:
      20% CLICKED
      60% OPENED (без клика)
      15% SENT
      5% BOUNCED
    """
    r = random.random()

    if r < 0.2:
        status = "CLICKED"
        opened_at = sent_at + timedelta(minutes=random.randint(1, 60))
        clicked_at = opened_at + timedelta(minutes=random.randint(1, 30))
    elif r < 0.8:
        status = "OPENED"
        opened_at = sent_at + timedelta(minutes=random.randint(1, 90))
        clicked_at = None
    elif r < 0.95:
        status = "SENT"
        opened_at = None
        clicked_at = None
    else:
        status = "BOUNCED"
        opened_at = None
        clicked_at = None

    return status, opened_at, clicked_at


def create_campaign_clients(campaign_id: int, client_ids: list[int]) -> int:
    """Создать записи в campaign_clients для выбранных клиентов."""
    now = datetime.now(timezone.utc)

    rows = []
    for client_id in client_ids:
        sent_at = now + timedelta(minutes=random.randint(-5, 5))
        status, opened_at, clicked_at = _simulate_status(sent_at)
        rows.append(
            {
                "campaign_id": campaign_id,
                "client_id": client_id,
                "sent_at": sent_at,
                "status": status,
                "opened_at": opened_at,
                "clicked_at": clicked_at,
            }
        )

    sql = text("""
        INSERT INTO campaign_clients
            (campaign_id, client_id, sent_at, status, opened_at, clicked_at)
        VALUES
            (:campaign_id, :client_id, :sent_at, :status, :opened_at, :clicked_at)
    """)

    with engine.begin() as conn:
        conn.execute(sql, rows)

    return len(rows)


def get_campaigns() -> pd.DataFrame:
    """Вернуть список кампаний (для аналитики)"""
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM campaigns ORDER BY created_at DESC", conn)
    return df

def get_campaign_clients_joined() -> pd.DataFrame:
    """
    Возвращает отправки писем с присоединёнными данными кампаний и клиентов.
    """
    sql = """
        SELECT
            cc.id         AS cc_id,
            cc.campaign_id,
            cc.client_id,
            cc.sent_at,
            cc.status     AS send_status,
            cc.opened_at,
            cc.clicked_at,
            c.name        AS campaign_name,
            c.status      AS campaign_status,
            c.created_at  AS campaign_created_at,
            cl.full_name,
            cl.gender,
            cl.email,
            cl.segment
        FROM campaign_clients cc
        JOIN campaigns c ON cc.campaign_id = c.id
        JOIN clients   cl ON cc.client_id   = cl.id
    """
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df

def get_reactivation_candidates(inactive_days: int = 30) -> pd.DataFrame:
    """
    Вернуть клиентов, которые давно не проявляли активность
    (не открывали и не кликали письма inactive_days дней).

    inactive_days: сколько дней без активности считаем "уснувшим" клиентом.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)

    sql = text("""
        WITH last_activity AS (
            SELECT
                c.id AS client_id,
                MAX(cc.sent_at) AS last_sent_at,
                MAX(
                    COALESCE(cc.opened_at, cc.clicked_at)
                ) AS last_activity_at
            FROM clients c
            LEFT JOIN campaign_clients cc ON cc.client_id = c.id
            GROUP BY c.id
        )
        SELECT
            c.id,
            c.full_name,
            c.email,
            c.gender,
            c.segment,
            la.last_sent_at,
            la.last_activity_at
        FROM clients c
        JOIN last_activity la ON la.client_id = c.id
        WHERE
            -- либо активности вообще не было, но что-то отправляли давно
            (
                la.last_activity_at IS NULL
                AND la.last_sent_at IS NOT NULL
                AND la.last_sent_at < :cutoff
            )
            OR
            -- либо активность была, но давно
            (
                la.last_activity_at IS NOT NULL
                AND la.last_activity_at < :cutoff
            )
        ORDER BY la.last_activity_at NULLS FIRST, la.last_sent_at
    """)

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"cutoff": cutoff})

    return df
