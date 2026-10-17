import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
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
HISTORY_DB_PATH = os.getenv("HISTORY_DB_PATH", str(Path(__file__).resolve().parent / "dbamonitor_history.sqlite3"))


def init_history_store():
    """Store monitoring samples locally, separate from the monitored PostgreSQL database."""
    path = Path(HISTORY_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS metric_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sampled_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            connected INTEGER NOT NULL,
            database_size TEXT,
            active_connections INTEGER,
            table_count INTEGER,
            index_count INTEGER,
            cache_hit_ratio REAL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metric_samples_sampled_at ON metric_samples(sampled_at)")
        conn.commit()


def save_metric_sample(data):
    metrics = data.get("metrics", {})
    status = data.get("status", {})
    with sqlite3.connect(HISTORY_DB_PATH, timeout=5) as conn:
        conn.execute("""INSERT INTO metric_samples
            (sampled_at, mode, connected, database_size, active_connections, table_count, index_count, cache_hit_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                datetime.now(timezone.utc).isoformat(), str(data.get("mode", "unknown")),
                1 if status.get("connected") else 0, str(metrics.get("database_size", "")),
                _int_or_none(metrics.get("active_connections")), _int_or_none(metrics.get("table_count")),
                _int_or_none(metrics.get("index_count")), _float_or_none(metrics.get("cache_hit_ratio"))))
        # Keep a bounded local history (30 days), avoiding unbounded growth.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn.execute("DELETE FROM metric_samples WHERE sampled_at < ?", (cutoff,))
        conn.commit()


def _int_or_none(value):
    try: return int(value) if value is not None and value != "—" else None
    except (ValueError, TypeError): return None


def _float_or_none(value):
    try: return float(value) if value is not None and value != "—" else None
    except (ValueError, TypeError): return None


init_history_store()

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
    data = collect_metrics()
    try:
        save_metric_sample(data)
    except (sqlite3.Error, OSError):
        # Monitoring should remain available even if local history storage is unavailable.
        data["history_warning"] = "Não foi possível gravar o histórico local nesta coleta."
    return jsonify(data)


@app.get("/api/history")
def history():
    try:
        limit = min(max(int(__import__("flask").request.args.get("limit", 100)), 1), 1000)
        with sqlite3.connect(HISTORY_DB_PATH, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT sampled_at, mode, connected, database_size, active_connections, table_count, index_count, cache_hit_ratio FROM metric_samples ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return jsonify({"persistent": True, "storage": "SQLite local", "retention_days": 30, "samples": [dict(row) for row in reversed(rows)]})
    except (sqlite3.Error, OSError, ValueError):
        return jsonify({"persistent": False, "samples": [], "message": "Histórico local indisponível."}), 500


def collect_diagnostics():
    result = {"available": False, "slow_queries": [], "blocking": [], "alerts": [], "notes": []}
    status = get_connection_status()
    if not status.get("connected"):
        result["notes"].append("Conecte o PostgreSQL para consultar estatísticas reais.")
        return result
    result["available"] = True
    try:
        with engine.connect() as conn:
            # Blocking relationships are observable with pg_stat_activity; query text is omitted to reduce data exposure.
            blockers = conn.execute(text("""
                SELECT blocked.pid AS blocked_pid, blocked.wait_event_type, blocked.wait_event,
                       now() - blocked.query_start AS waiting_for,
                       blocker.pid AS blocker_pid, blocker.state AS blocker_state
                FROM pg_stat_activity blocked
                JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS p(blocker_pid) ON true
                JOIN pg_stat_activity blocker ON blocker.pid = p.blocker_pid
                WHERE blocked.datname = current_database() AND blocked.pid <> pg_backend_pid()
                ORDER BY blocked.query_start NULLS LAST LIMIT 50
            """)).mappings().all()
            result["blocking"] = [{"blocked_pid": r["blocked_pid"], "wait_event_type": r["wait_event_type"], "wait_event": r["wait_event"], "waiting_for": str(r["waiting_for"]), "blocker_pid": r["blocker_pid"], "blocker_state": r["blocker_state"]} for r in blockers]
            # pg_stat_statements is optional and may not be installed or granted; never enable it automatically.
            try:
                slow = conn.execute(text("""
                    SELECT queryid::text AS queryid, calls, round(total_exec_time::numeric, 2) AS total_ms,
                           round(mean_exec_time::numeric, 2) AS mean_ms, rows
                    FROM pg_stat_statements
                    WHERE query NOT ILIKE '%pg_stat_statements%'
                    ORDER BY mean_exec_time DESC LIMIT 10
                """)).mappings().all()
                result["slow_queries"] = [{"queryid": r["queryid"], "calls": int(r["calls"] or 0), "total_ms": float(r["total_ms"] or 0), "mean_ms": float(r["mean_ms"] or 0), "rows": int(r["rows"] or 0)} for r in slow]
                result["slow_queries_available"] = True
            except SQLAlchemyError:
                result["slow_queries_available"] = False
                result["notes"].append("Consultas lentas indisponíveis: pg_stat_statements não está instalado/habilitado ou faltam permissões. Não foi ativado automaticamente.")
        if result["blocking"]:
            result["alerts"].append({"severity": "warning", "title": "Sessões bloqueadas detectadas", "detail": f"{len(result['blocking'])} relação(ões) de bloqueio encontrada(s). Investigue antes de encerrar sessões."})
        if not result["blocking"]:
            result["alerts"].append({"severity": "ok", "title": "Nenhum bloqueio detectado nesta coleta", "detail": "É uma fotografia do momento; bloqueios transitórios podem não aparecer."})
        if not result.get("slow_queries_available"):
            result["alerts"].append({"severity": "info", "title": "Análise de consultas limitada", "detail": "Habilite pg_stat_statements conforme os recursos e permissões do provedor para obter estatísticas agregadas de consultas."})
    except SQLAlchemyError as exc:
        result["available"] = False
        result["notes"].append(f"Falha ao consultar diagnóstico ({exc.__class__.__name__}). Verifique permissões de leitura das estatísticas.")
    return result


@app.get("/api/diagnostics")
def diagnostics():
    return jsonify(collect_diagnostics())


@app.get("/api/backups")
def backups():
    status = get_connection_status()
    result = {"available": bool(status.get("connected")), "provider": "PostgreSQL/Neon", "checks": [], "warning": "O DBAMonitor não cria backups nem executa restaurações automaticamente. Confirme backups e retenção no painel do provedor; restauração deve ser testada em banco separado.", "recommendations": ["Confirmar política de backup/PITR e retenção no painel Neon.", "Registrar data e resultado do último backup verificável.", "Executar restauração de teste em um banco isolado antes de confiar no plano de recuperação."]}
    if not status.get("connected"):
        result["checks"].append({"name": "Conectividade", "status": "indisponível", "detail": status.get("message", "Banco desconectado")})
        return jsonify(result)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT pg_is_in_recovery() AS in_recovery")).mappings().one()
            result["checks"].append({"name": "Conexão com banco", "status": "ok", "detail": "O banco respondeu à consulta de verificação."})
            result["checks"].append({"name": "Papel da instância", "status": "info", "detail": "Em recuperação: " + ("sim" if row["in_recovery"] else "não")})
    except SQLAlchemyError as exc:
        result["checks"].append({"name": "Conectividade", "status": "falha", "detail": f"Consulta falhou ({exc.__class__.__name__})."})
    result["checks"].append({"name": "Backup e restauração", "status": "verificação manual necessária", "detail": "A consulta SQL não comprova que um backup restaurável exista."})
    return jsonify(result)


@app.get("/api/db-check")
def db_check():
    return jsonify(get_connection_status())


if __name__ == "__main__":
    # 0.0.0.0 is required for GitHub Codespaces port forwarding.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=APP_ENV == "development")
