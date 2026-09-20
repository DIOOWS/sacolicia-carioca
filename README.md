# Sacolícia Carioca

PWA de pedidos B2B com áreas administrativas e de cliente separadas.

## Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python seed.py
python run.py
```

Acesse `http://127.0.0.1:5000`.

### Acessos iniciais

Copie `.env.example` para `.env` e defina `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
`DEMO_CLIENT_EMAIL` e `DEMO_CLIENT_PASSWORD` antes de executar `python seed.py`.
Senhas reais não devem ser enviadas para o GitHub.

## Bancos

- Local: SQLite, configurado automaticamente.
- Produção: defina `DATABASE_URL` com a conexão PostgreSQL do Supabase.

O projeto inclui `Procfile` para Render e Railway.

## Branches

- `main`: versão estável ligada à produção.
- `develop`: desenvolvimento e homologação mobile antes da publicação.

O arquivo `render.yaml` configura o serviço de produção usando a branch `main`.

## Escopo desta primeira base

- Login sem cadastro público.
- Perfis administrativo e cliente protegidos no servidor.
- Cliente vinculado a vários estabelecimentos.
- Produtos com preço, estoque e disponibilidade.
- Pedidos preparados para aprovação do vendedor.
- Dashboard administrativo e portal mobile do cliente.
- Manifesto e service worker para instalação como PWA.
