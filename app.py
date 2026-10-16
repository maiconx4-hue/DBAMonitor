import os
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from urllib.parse import urlparse

load_dotenv()
app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
APP_ENV = os.getenv("APP_ENV", "development").lower()
engine = None
db_error = None

if DATABASE_URL:
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
            connect_args={"connect_timeout": 5},
        )
    except Exception as exc:
        db_error = f"Não foi possível preparar a conexão: {exc.__class__.__name__}"


def get_connection_status():
    if not DATABASE_URL:
        return {"connected": False, "mode": "demo", "message": "Sem DATABASE_URL: exibindo demonstração; nenhum banco real foi consultado."}
    if engine is None:
        return {"connected": False, "mode": "configured", "message": db_error or "Configuração inválida."}
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
            current_db = conn.execute(text("SELECT current_database()")).scalar_one()
            current_user = conn.execute(text("SELECT current_user")).scalar_one()
            read_only = conn.execute(text("SHOW default_transaction_read_only")).scalar_one()
        return {
            "connected": True, "mode": "postgresql",
            "database": current_db, "user": current_user,
            "version": version.split(",")[0],
            "default_read_only": read_only,
            "message": "Conexão validada. O painel executa somente consultas de leitura."
        }
    except SQLAlchemyError as exc:
        return {"connected": False, "mode": "configured", "message": f"Falha de conexão/consulta: {exc.__class__.__name__}. Confira DATABASE_URL, rede e permissões."}


def collect_metrics():
    status = get_connection_status()
    if not status["connected"]:
        return {
            "status": status,
            "metrics": {
                "database_size": "Demo",
                "active_connections": 0,
                "table_count": 0,
                "index_count": 0,
                "cache_hit_ratio": None,
            },
            "tables": [],
            "activity": [],
            "mode": "demo",
        }

    # Only SELECT queries. These may require permissions to read PostgreSQL statistics views.
    try:
        with engine.connect() as conn:
            size_bytes = conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
            relation_counts = conn.execute(text("""
                SELECT
                  COUNT(*) FILTER (WHERE c.relkind IN ('r','p')) AS tables,
                  COUNT(*) FILTER (WHERE c.relkind = 'i') AS indexes
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
            """)).mappings().one()
            # pg_stat_activity may show only limited detail depending on the connecting role.
            active_connections = conn.execute(text("""
                SELECT COUNT(*) FROM pg_stat_activity
                WHERE datname = current_database() AND state = 'active'
            """)).scalar_one()
            tables = conn.execute(text("""
                SELECT schemaname, relname AS table_name,
                       pg_total_relation_size(format('%I.%I', schemaname, relname)::regclass) AS total_bytes,
                       COALESCE(seq_scan, 0) AS sequential_scans,
                       COALESCE(idx_scan, 0) AS index_scans
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(format('%I.%I', schemaname, relname)::regclass) DESC
                LIMIT 10
            """)).mappings().all()
            cache_row = conn.execute(text("""
                SELECT
                  SUM(blks_hit)::numeric AS hits,
                  SUM(blks_read)::numeric AS reads
                FROM pg_stat_database WHERE datname = current_database()
            """)).mappings().one()
            hits = cache_row["hits"] or 0
            reads = cache_row["reads"] or 0
            ratio = round(float(hits) / float(hits + reads) * 100, 2) if hits + reads else None

        def human_bytes(value):
            units = ["B", "KB", "MB", "GB", "TB"]
            value = float(value or 0)
            for unit in units:
                if value < 1024 or unit == "TB":
                    return f"{value:.1f} {unit}"
                value /= 1024
        return {
            "status": status,
            "metrics": {
                "database_size": human_bytes(size_bytes),
                "active_connections": int(active_connections),
                "table_count": int(relation_counts["tables"]),
                "index_count": int(relation_counts["indexes"]),
                "cache_hit_ratio": ratio,
            },
            "tables": [{
                "schema": row["schemaname"],
                "name": row["table_name"],
                "size": human_bytes(row["total_bytes"]),
                "seq_scans": int(row["sequential_scans"]),
                "idx_scans": int(row["index_scans"]),
            } for row in tables],
            "activity": [],
            "mode": "postgresql",
        }
    except SQLAlchemyError as exc:
        return {
            "status": {**status, "message": f"Conectado, mas uma consulta de métricas falhou ({exc.__class__.__name__}). Verifique as permissões de leitura das estatísticas."},
            "metrics": {"database_size": "Disponível", "active_connections": "—", "table_count": "—", "index_count": "—", "cache_hit_ratio": None},
            "tables": [], "activity": [], "mode": "partial"
        }


@app.get("/")
def index():
    return render_template("index.html", now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "app": "DBAMonitor", "time_utc": datetime.now(timezone.utc).isoformat()})


@app.get("/api/overview")
def overview():
    return jsonify(collect_metrics())


@app.get("/api/db-check")
def db_check():
    return jsonify(get_connection_status())


if __name__ == "__main__":
    # 0.0.0.0 is required for GitHub Codespaces port forwarding.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=APP_ENV == "development")
