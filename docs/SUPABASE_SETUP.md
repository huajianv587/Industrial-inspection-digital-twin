# Supabase 项目接入

## 项目隔离

为巡检平台使用单独的 Supabase project。不要复用其他应用的 staging/production 项目。部署前核对 project ref、数据库主机、Auth issuer 和 URL 属于同一项目；runtime preflight 与 Alembic 会分别检查运行角色和 migration owner 连接的 project ref。项目 ref 未确认前，不要执行本目录的 Alembic migration。

## 数据库角色

`SUPABASE_DB_URL` 仅供 migration 使用，使用 Supabase Connect 提供的 owner/admin PostgreSQL URL。API 与 worker 使用 `SUPABASE_APP_DB_URL`，对应专用最小权限角色。首次 migration 前，下面 SQL 由项目管理员在 SQL Editor 创建角色；替换密码占位符后，不要把 SQL、密码或连接串提交到仓库或聊天。

```sql
CREATE ROLE inspection_app LOGIN NOBYPASSRLS PASSWORD '<generate-a-unique-url-encoded-password>';
GRANT CONNECT ON DATABASE postgres TO inspection_app;
GRANT USAGE ON SCHEMA public TO inspection_app;
```

首次初始化顺序：创建 `inspection_app` 角色；在 `.env` 设置 owner/admin 与运行角色连接串；用 `SUPABASE_DB_URL` 执行 migration。初始迁移会为 `missions`/`work_orders` 授予 SELECT/INSERT/UPDATE，为 `artifacts`/`audit_events` 仅授予 SELECT/INSERT，并在业务表上启用 RLS，只给 `inspection_app` 建立访问策略。运行账号没有建表、删除或审计更新权限。未来新增表也必须显式配置最小 SQL 权限、启用 RLS 并创建最小范围策略；不要使用宽泛的默认权限或把 DDL 权限授予运行账号。

如果该 Supabase 项目采用非 `postgres` 的 migration owner，应将 `ALTER DEFAULT PRIVILEGES FOR ROLE postgres` 改成实际表 owner，并确保 migration 与运行角色使用的 schema 一致。

## Auth 与应用角色

- 启用 Supabase Auth Email/Password provider，并创建获授权用户。
- 生产环境关闭公开注册；此控制台没有自助注册流程，只允许管理员通过受信任的 Supabase 管理界面/API 创建或邀请账户。
- `make validate-auth` 只读读取 `/auth/v1/settings`，要求 `disable_signup=true` 且 `mailer_autoconfirm=false`；生产 Compose preflight 也执行同一检查，并在数据库迁移前拒绝不符合策略的配置。
- `SUPABASE_URL` 与 `OIDC_ISSUER` 必须属于同一项目；issuer 形式为 `https://<project-ref>.supabase.co/auth/v1`，audience 为 `authenticated`。
- 必须在受信任的 `app_metadata.roles` 中显式设置 `admin`、`operator`、`reviewer` 或 `viewer`；缺少有效角色的有效 token 会收到 HTTP 403。客户端可修改的 `user_metadata` 不参与授权。
- 可以给同一账户分配多个角色，API 按受信任角色的权限并集授权；审计事件的 `actor_role` 仍记录一个确定性的主角色。
- 前端构建只使用 anon/publishable key。数据库密码和 Supabase service-role key 均不得进入 `web/`、镜像构建参数或浏览器。

真实用户验收使用单独的非生产测试账号，并授予完成只读验证所需的 `app_metadata.roles`。将测试邮箱与密码写入 Git 忽略的 `secrets/supabase_e2e_email` 和 `secrets/supabase_e2e_password`，文件权限设为 `0600`；在 `.env` 中启用对应 `SUPABASE_E2E_*_SECRET_FILE` 路径后运行 `make smoke-auth-api`。该命令只执行 password grant 登录和 dashboard/sites/missions/work-orders GET；角色缺失或 API 拒绝会失败。它不创建用户、不写巡检任务，也不验证 Storage 服务账号。

## Storage 制品 bucket

Migration `20261020_0004` 创建/校验私有 `inspection-artifacts` bucket，并为 `authenticated` 身份建立限定到该 bucket、且要求 `app_metadata.inspection_storage=service` 的 SELECT/INSERT/UPDATE policies。downgrade 只移除本 migration 的 policies，不删除 bucket 或对象。部署前核对目标项目，并在确认后执行 `alembic upgrade head`；不要在未确认项目的情况下迁移。

在同一 Supabase 项目创建专用于 Storage 的 Auth Email/Password 用户。通过可信管理界面/API 给该用户设置 `app_metadata.inspection_storage` 为 `service`，不要设置客户端可修改的 `user_metadata`，也不要给它 `service_role` 权限。将邮箱与高熵密码分别写入 `secrets/supabase_storage_email` 和 `secrets/supabase_storage_password`。不要把这些文件内容粘贴到终端命令、聊天或仓库。

`SUPABASE_STORAGE_ENDPOINT` 必须是该项目的 S3 endpoint；`SUPABASE_STORAGE_REGION` 必须填写该项目 Storage S3 设置显示的 region，不能直接照抄示例值。上传对象采用 `{run_id}/{sha256}` 内容寻址路径；读取和下载会对实际对象字节流计算 SHA-256，不依赖 S3 自定义 metadata。Storage 操作依赖的真实读写权限仍须通过目标项目 smoke test 验证。

API/worker Compose services 为导入只读 Compose secret 会以 root 启动 entrypoint；entrypoint 将 secrets 复制到 `/run/inspection-secrets` tmpfs 并设置为 UID 10001 可读，随后用 `gosu` 降权运行应用。Slurm SSH key 与 `known_hosts` 不挂到默认 offline worker；切换 Slurm 时使用 `docker-compose.slurm.yml` overlay，并把宿主机文件放在 Git 忽略的 `secrets/` 目录。

### Storage 对象读写 smoke

配置好 Supabase 项目、数据库连接和 Storage 专用 Auth 用户凭据后运行 `make smoke-storage`。命令会先验证数据库 URL 属于该 Supabase 项目及 Storage endpoint/bucket 配置，再执行 bucket 探测、上传、重复上传、下载和 SHA-256 校验；不会写数据库。为避免向 Storage 身份授予 DELETE 权限，smoke 使用固定内容和固定 `storage-smoke-v1` run ID，成功后保留单个可重复复用/验证的 smoke 标记对象 `storage-smoke-v1/<sha256>`。该对象不是巡检任务或业务制品。命令失败时不应将 Storage I/O 标记为已验证。

## 连接核验

使用该 Supabase 项目连接面板提供的 IPv4 session pooler URI。将项目的 SSL root certificate 保存为 `certs/supabase-root.crt`；镜像会打包这个公开 CA 证书，数据库连接强制启用 `verify-full` 并校验主机名。证书轮换时同步更新该文件。

填好被 Git 忽略的 `.env` 并预先创建 `inspection_app` 角色后，先检查目标 project ref 但不要打印完整连接串，再执行：

```bash
docker compose run --rm migrate alembic upgrade head
make validate-storage
docker compose up --build -d
curl --fail http://localhost:8080/readyz
```

确认迁移记录、bucket 与 policies 都出现在巡检专用项目中后，再用 Storage 专用账号验证对象写入、读取、校验失败和幂等行为。确认迁移记录和表都出现在巡检专用项目中后，才继续创建测试任务。运行此核验需要有效 Supabase 配置；本地 SQLite/Storage mock 不可用于替代。
