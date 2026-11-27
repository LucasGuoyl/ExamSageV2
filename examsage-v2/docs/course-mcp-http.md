# 托管课程工具的 HTTP 接口

课程宿主可以通过 `POST /mcp` 提供与项目内学生包 0.6.4 共用的 17 个只读工具，包括逐题回测、按小问浏览往卷和核对题内短引。宿主负责对话模型和学生登录。押题宝从课程快照返回证据、原图和复算结果。学生端无需提供模型 API Key。

## 本机验证

在押题宝项目已配置的 Python 环境中运行以下命令。课程编号可重复传入。省略 `--course` 时只列出当前操作系统账号自己导入的课程。

```powershell
python -m examsage serve-mcp-local --course grt --course ses
```

将本机 MCP HTTP 客户端指向 `http://127.0.0.1:8770/mcp`。本机入口按当前操作系统账号选择资料，仅监听回环地址。在当前沙箱中已验证监听成功，测试客户端连接时 Windows 返回 10013。普通 ChatGPT 网页仍需要它能访问的 HTTPS 地址。

## 学校或平台宿主

项目提供 WSGI 应用工厂。下面两个域名仅用于演示配置，运行时由运营方换成实际地址。

```python
from pathlib import Path
from examsage.mcp_http import create_course_mcp

course_application = create_course_mcp(
    Path("data"),
    Path("data/hosted-students"),
    origin="https://courses.example.edu",
    authorization_server="https://login.example.edu/students",
)
```

将应用交给现有 WSGI 宿主。默认公开路径为 `/mcp`。课程路由每次只接受上游认证中间件设置的 `environ["examsage.principal"]`，类型为 `examsage.plugin_tools.Principal`。上游须在请求到达课程路由之前验证面向该资源的身份与授权，由稳定的发行方和用户标识构造唯一学生身份，并从服务端课程登记中取得公共课编号。普通 HTTP 请求头和模型工具参数均不能设置该对象。浏览器跨来源访问时，通过 `allowed_origins` 配置具体站点。网关需放行这些站点的预检、公开发现和初始 401 挑战。前端可以读取挑战并在已授权的课程请求内发送 Authorization 头。

宿主配置了授权服务后，匿名访问课程接口可得到 `401` 和 `WWW-Authenticate` 挑战。授权资源说明位于 `/.well-known/oauth-protected-resource/mcp`，给出课程资源与学校授权服务的地址。这个说明对接的是外部已有的认证服务。课程应用自身不会签发令牌。代理应保留或生成配置中指定的 Host，转发后的公开路径应与说明中的资源地址一致。[MCP 授权发现规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

如果 WSGI 网关把应用挂在 `/school`，它应将该前缀放在标准 `SCRIPT_NAME` 中。此时受保护的资源是 `/school/mcp`，挑战会给出该挂载下可直接访问的元数据地址。为支持按 RFC 从根路径推导地址的客户端，网关还应将 `/.well-known/oauth-protected-resource/school/mcp` 映射到同一说明处理器，保留相同的 `SCRIPT_NAME`。[RFC 9728 的发现地址规则](https://www.rfc-editor.org/rfc/rfc9728.html#section-3.1)

私课归属取决于同一学生根目录下的宿主身份。学校账户与本机 Windows 账户使用各自的身份标识；迁移学生资料前需要真实的账号归属确认。公共课在每个请求重新检查，已经撤销的课程会从下一次列课和读页中消失。

学生导入时登记的课程体系和大纲版本可通过 `list_courses` 与 `get_course_profile` 查看。在项目内 HTTP 测试中，同一学生的三门同名课程分别返回高中版本、本科版本和未登记状态。另一学生的三次课程档案查询均被拒绝。进程内 HTTP 验收（本地验收记录）

## 客户端可检查的行为

先进行 MCP `initialize` 协商，再发送 `notifications/initialized`，随后可以列工具、列课、读原页并追问。当前支持 `2025-11-25`，后续请求带上 `MCP-Protocol-Version`。POST 的内容类型为 `application/json`，Accept 列出 `application/json, text/event-stream`。本实现使用无会话的 JSON 响应，通知返回 202，GET 事件流返回 405。所有工具按请求重新选定学生范围。[MCP HTTP 传输规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

物理、数学、文学、历史、SES 和地球动力学的 12 次首问和追问（本地验收记录）已在最终代码复跑。最终复验（本地验收记录）记录每门课的资料快照与实际请求。真实 HTTPS 部署、学校授权流程、ChatGPT 网页连接和学生从网页调回课程原图仍需逐项联调。

## 在对话中查看引用原页

学生可以追问“打开刚才引用的地球动力学第二讲第 17 页，我想检查泊松比的指数”。当宿主调用 `get_source_page` 或 `get_source_image` 时，支持 MCP Apps 的客户端可以显示来源卡。卡上标出文件名和物理页，展开“来源与核查说明”可见来源编号。若宿主允许组件调用工具，学生可以在同一页的提取文字与完整原图间切换。重新查询发现课程快照或来源已变化时，卡片会要求从对话重新打开。

图片初始完整显示，点击“放大原图”后可以滚动查看局部。文学课的原始诗行与空行保留。具有后补导读但原始提取不足的页会保留原文缺口。未加载组件的客户端仍可读取工具原有的文字、引用和可用原图。

HTTP 服务通过工具的 `_meta.ui.resourceUri` 注册静态 HTML 资源 `ui://examsage/source-page-v1.html`。资源文件只包含界面。课程内容由宿主随实际工具结果传入，点“查看本页原图”会在当前学生授权下再次调用并核对来源。组件在宿主 iframe 内通过 MCP Apps 消息通信。[OpenAI 组件说明](https://developers.openai.com/plugins/build/chatgpt-ui) · [MCP Apps 规范](https://modelcontextprotocol.io/extensions/apps/overview)

可以直接打开七门课的来源卡试用（本地验收记录）。该单文件包含本轮选定原页的工具回执，切换课程、看图和放大均在本地回放。实际课程服务会在请求时重新核验学生授权。

本地真实 Chromium 已通过模拟宿主验证交互。可以查看地球动力学桌面截图（本地验收记录）、文学手机截图（本地验收记录）和学生浏览器记录（本地验收记录）。普通 ChatGPT 网页的正式账号接入与实际渲染尚待联调。
