# Serve course tools over HTTP

A course host can expose the student plugin's 17 read-only tools from the 0.6.4 pilot at `POST /mcp`. The tools retrieve evidence, original-page images and recalculations from a course snapshot. They support question-level backtesting, browsing past-paper subquestions and checking exact passages. The host supplies the conversation model and student authentication. Students do not configure a model API key in ExamSage.

## Try a local client

Run the command in a configured ExamSage Python environment. Repeat `--course` to make several registered courses available. If omitted, only courses imported under the current operating-system account are listed.

```powershell
python -m examsage serve-mcp-local --course grt --course ses
```

Point the local HTTP MCP client at `http://127.0.0.1:8770/mcp`. This service listens on loopback and selects material for the current operating-system user. A hosted ChatGPT client would need a reachable HTTPS endpoint. In the original sandbox pilot, the listener started but a Windows client connection returned error 10013.

## Configure a school or platform host

Mount the WSGI application in the institution's own host. Replace the example origins with the institution's public course endpoint and authorization server.

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

The default public route is `/mcp`. For each request, the course route accepts an `examsage.plugin_tools.Principal` set in `environ["examsage.principal"]` by upstream authentication middleware. The middleware must validate identity and authorization for this resource before the request reaches the course route. Construct a unique student identity from a stable issuer and user identifier. Obtain authorized shared-course IDs from the server-side enrolment register. Request headers and model tool arguments cannot set the principal.

Use `allowed_origins` for specific browser origins. The gateway must forward their preflight requests, public discovery requests and the initial 401 challenge. An authorized frontend can read the challenge and send its Authorization header on subsequent course requests.

When an authorization server is configured, an anonymous course request receives a 401 with a `WWW-Authenticate` challenge. The course service publishes OAuth protected-resource metadata at `/.well-known/oauth-protected-resource/mcp`. It identifies the course resource and the external authorization server responsible for issuing tokens. A reverse proxy must preserve or generate the configured Host and forward a public path consistent with the resource URL. [MCP authorization discovery](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

For a deployment under `/school`, the gateway sets the WSGI `SCRIPT_NAME` to that prefix. The protected resource becomes `/school/mcp` and the challenge advertises its metadata address. Clients deriving the metadata URL from the origin root also require `/.well-known/oauth-protected-resource/school/mcp` mapped to the same handler with the same `SCRIPT_NAME`. [RFC 9728 discovery rules](https://www.rfc-editor.org/rfc/rfc9728.html#section-3.1)

Private-course ownership depends on the host identity under a given student root. A school account and a Windows account have different identifiers. Verify actual ownership before migrating a workspace between them. Shared-course permissions are checked on every request, including requests to list courses or retrieve a page.

## Check the client protocol

Negotiate MCP with `initialize`, send `notifications/initialized`, then list tools, list courses and request sources. The implemented version is `2025-11-25`. Send `MCP-Protocol-Version` on subsequent requests. POST uses `application/json` with an Accept header listing `application/json, text/event-stream`. This implementation returns stateless JSON responses, 202 for notifications and 405 for a GET event stream. Each tool request reselects the authorized student scope. [MCP HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

Use `list_courses` and `get_course_profile` to inspect the imported curriculum and syllabus version. In-process tests distinguished three identically named courses belonging to one student, with school-level, university-level and unspecified curricula. The same three profile lookups by another student were rejected.

Twelve first questions and follow-ups were repeated against the local service across physics, mathematics, literature, history, sustainable electrical systems and geodynamics. The local record identifies the snapshot and request for each course. A public HTTPS deployment, institutional sign-in, a hosted ChatGPT client and returning a course image inside that client require separate end-to-end checks.

## Open the page behind a citation

A student might ask “Open page 17 of the second geodynamics lecture. I want to check the exponent on Poisson's ratio.” A client supporting MCP Apps can show a source card when the host calls `get_source_page` or `get_source_image`. The card gives the filename and physical page. Its source and review details include the source ID. If the host permits component tool calls, the student can switch between the extracted text and the original image. Changes in the course snapshot or source require reopening the card from the conversation.

The image starts fitted to the card. Zoom in to inspect a detail. Poetry preserves line and stanza breaks, and an extraction gap stays visible even when a later study note exists. Clients without the component can consume the tool's text, references and available image directly.

The tool registers the static HTML resource `ui://examsage/source-page-v1.html` with `_meta.ui.resourceUri`. The resource contains the interface. The host supplies the course content through its tool result. Requesting the original image calls the tool again under the current student scope and checks the source. The component communicates with the host iframe using MCP Apps messages. [OpenAI component guide](https://developers.openai.com/plugins/build/chatgpt-ui) · [MCP Apps overview](https://modelcontextprotocol.io/extensions/apps/overview)

A seven-course local replay used selected tool receipts to test course switching, opening an image and zooming. Chromium checks exercised a simulated host with geodynamics on desktop and literature at a mobile viewport. The replay and screenshots remain with the local test materials. They cover the component interaction in that test environment.
