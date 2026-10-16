# DBAMonitor v0.1

Dashboard inicial para monitoramento **somente de leitura** do PostgreSQL, criado para o Projeto Integrador de Administração de Banco de Dados e futura análise do Studio OS 5.0.

## Funcionalidades desta versão

- Dashboard responsivo com gráficos.
- Endpoint de saúde `/api/health`.
- Endpoint de métricas `/api/overview`.
- Verificação de conexão `/api/db-check`.
- Sem `DATABASE_URL`, funciona em modo demonstração e informa que não consultou o banco real.
- Com `DATABASE_URL`, consulta informações gerais do PostgreSQL, tamanho do banco, contagem de tabelas/índices, conexões ativas, estatísticas de cache e tabelas de maior tamanho.
- Testes iniciais com pytest.

## Segurança

1. Não use a conta proprietária/admin do banco de produção.
2. Crie/solicite uma credencial dedicada com privilégios mínimos de leitura.
3. Não faça commit do arquivo `.env`.
4. Não cole a URL de conexão em chats, issues ou código.
5. Esta versão não cria, altera ou exclui tabelas/índices. As consultas de estatísticas podem exigir privilégios que variam por versão e provedor.
6. Faça a primeira conexão em ambiente seguro. O Codespace e o banco precisam ter conectividade de rede entre si.
7. O painel é um protótipo de diagnóstico, não um sistema de monitoramento empresarial endurecido para produção.

## Executar no GitHub Codespaces ou Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m pytest -q
python app.py
```

Abra a aba **Ports** e encaminhe a porta `8000` para acessar o dashboard.

No Windows PowerShell, a ativação do ambiente virtual é:

```powershell
.venv\Scripts\Activate.ps1
```

## Conectar ao PostgreSQL

Edite `.env` localmente e defina `DATABASE_URL` usando o formato:

```text
postgresql+psycopg://USUARIO:SENHA@HOST:5432/NOME_DO_BANCO?sslmode=require
```

Substitua os campos localmente. Não compartilhe a senha. Codifique caracteres especiais da senha para URL quando necessário. Use o modo SSL exigido pelo provedor. Reinicie a aplicação após editar `.env`.

Antes de conectar ao Studio OS, confirme o provedor, a conectividade do Codespace e a disponibilidade de uma conta dedicada somente leitura. Não use uma credencial de proprietário para o primeiro diagnóstico.

## Rotina de validação antes de versionar

```bash
python -m compileall -q .
python -m pytest -q
git diff --check
git status --short
git diff
```

## Próximas etapas planejadas

1. Testar conexão real de leitura com PostgreSQL.
2. Documentar permissões exigidas por cada métrica.
3. Adicionar métricas de consultas lentas com `pg_stat_statements`, se disponível.
4. Adicionar histórico de coleta e comparações.
5. Criar testes de integração com banco de teste isolado.
6. Não executar otimizações em produção sem evidências, backup e plano de reversão.
