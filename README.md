# DBAMonitor v0.4 — Monitoramento e diagnóstico PostgreSQL

Aplicação Flask para monitorar um PostgreSQL real por meio de consultas de leitura. O painel inclui métricas básicas, histórico persistente local, detecção de bloqueios, consulta opcional a estatísticas de consultas e checklist de backup/recuperação.

## Requisitos
- Python 3.11 ou superior (testado no projeto com Python 3.13)
- PostgreSQL acessível pela aplicação
- Dependências em `requirements.txt`

## Instalação local (Windows PowerShell)
```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```
Edite `.env` localmente e configure `DATABASE_URL`. Nunca compartilhe nem envie `.env` ao GitHub. Use preferencialmente um usuário PostgreSQL dedicado com privilégios mínimos e acesso somente leitura às estatísticas necessárias.

## Executar
```powershell
python app.py
```
Abra `http://127.0.0.1:8000`.

## Testes e validação
```powershell
python -m compileall -q .
python -m pytest -q
git diff --check
```

## Recursos
- Visão geral: tamanho do banco, conexões, contagem de tabelas/índices, cache hit ratio e tabelas de maior tamanho.
- Atualização automática a cada 30 segundos.
- Histórico persistente em SQLite local (`dbamonitor_history.sqlite3`), retido por 30 dias. O histórico sobrevive a fechar/reabrir o navegador e é gravado quando `/api/overview` é consultado. Para monitoramento contínuo, mantenha o serviço ativo e configure um processo de coleta agendado/monitor externo; a coleta atual acontece quando o dashboard solicita métricas.
- Diagnóstico de bloqueios via `pg_stat_activity` e `pg_blocking_pids()` quando permitido.
- Consultas agregadas por maior tempo médio via `pg_stat_statements`, apenas se a extensão estiver habilitada e o usuário tiver permissões. O sistema não ativa extensões nem expõe o texto das consultas.
- Checklist de backup/recuperação e verificação de conectividade.

## Limitações importantes
- A aplicação não executa comandos de alteração, não encerra sessões e não cria/restaura backups.
- A conexão bem-sucedida a um banco não comprova que exista um backup restaurável. Confirme a política de backup/PITR e retenção no console do provedor (por exemplo, Neon) e faça teste de restauração em um banco isolado.
- Estatísticas de consultas podem não estar disponíveis em serviços gerenciados ou sem permissões apropriadas. A ausência de `pg_stat_statements` é informada, não corrigida automaticamente.
- Histórico SQLite é local ao servidor em que a aplicação roda. Em hospedagem efêmera/multi-instância, o arquivo pode não persistir; use armazenamento persistente ou uma base de monitoramento dedicada.
- Métricas são amostras, não garantias de ausência de problemas. Alertas são sinais para investigação, não recomendações automáticas para alterar o banco.

## Endpoints
- `GET /api/health`
- `GET /api/overview`
- `GET /api/db-check`
- `GET /api/history?limit=100`
- `GET /api/diagnostics`
- `GET /api/backups`

## Segurança
Não versionar `.env`, credenciais, dumps de produção ou o banco SQLite de histórico. Comece com permissões mínimas; não use a conta proprietária do banco para monitoramento contínuo.
