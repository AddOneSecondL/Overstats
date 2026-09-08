# SCF 容器部署

普通部署继续使用 `python run.py`。SCF 使用专用入口，关闭数据库写入，并从私有 COS 加载账号池。

## 从源码构建

将以下示例中的仓库、镜像、地域和函数名替换为自己的配置：

```powershell
git clone --branch main <repository-url> overstats-scf
Set-Location overstats-scf
git pull --ff-only origin main
$revision = git rev-parse --short HEAD
$image = "<registry>/<namespace>/<image>:main-$revision"
docker build --platform linux/amd64 -t $image .
docker push $image
python -m pip install tencentcloud-sdk-python-scf
python .\update_scf_images.py --region <region> --names <function-name> --image $image
# 检查预览后，添加 --apply 执行；--names 支持多个函数名
```

构建阶段自动获取 query_tool 配置和资源，下载不完整会终止构建。生成资源只留在镜像，不提交仓库。每次发布使用新镜像标签，避免相同标签被更新脚本跳过。

## 函数配置

使用容器镜像 Web 函数，端口 9000，ENTRYPOINT/CMD 留空。按实际负载设置内存和超时。每个函数使用独立账号池时，应限制实例数，避免多个实例重复使用同一池。

配置以下环境变量，并为运行角色授予指定 COS 对象的 `cos:GetObject` 权限：

- `OVERSTATS_ACCOUNTS_COS_REGION`：存储桶地域。
- `OVERSTATS_ACCOUNTS_COS_BUCKET`：私有存储桶名称。
- `OVERSTATS_ACCOUNTS_COS_KEY`：账号 JSON 对象键。

账号文件为 JSON 数组，每项包含 `role_id`、`token`，可选 `name`。role_id 必须为正整数，token 非空，name 和 role_id 不重复。真实账号只放私有 COS，不放进 Git 或镜像。函数通过 SCF 临时运行角色凭据读取对象，无需配置长期 SecretId/SecretKey。

首次请求仍需加载账号和创建 core，之后复用进程。SCF 专用入口暂停运行时 query_tool 更新及资源批量初始化，使用构建时打包的资源。普通启动不受此开关影响。更新账号或资源后需重新部署。

## 批量更新

更新脚本必须显式提供 `--region`、`--names`，以及 `--image` 或 `--memory`。默认仅预览，添加 `--apply` 才执行。支持 `--namespace`。凭据通过环境变量或隐藏输入获取，不保存；本地进度文件已加入忽略规则。

脚本更新 `$LATEST`。若函数 URL 的别名绑定固定版本，需要另行发布并切换别名。更新后验证健康检查和实际查询。
