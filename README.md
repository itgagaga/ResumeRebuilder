# Resume Rebuilder · 简历重建工作台

根据 [开发文档.md](开发文档.md) V1.1 实现的本地首版。Python + FastAPI 负责解析、OCR、存储和导出；React + TypeScript 渲染 HTML/CSS 编辑页面。文件保存在本机 `projects/`，服务只监听 `127.0.0.1:8765`。

## 启动

本次开发已安装 Python / 前端依赖并构建界面，当前机器的 Edge 已验证能用于 PDF 导出。在此文件夹的 PowerShell 中运行：

```powershell
.\start.ps1
```

浏览器访问 <http://127.0.0.1:8765>。按 Ctrl+C 停止服务。不自动打开浏览器时使用 `.\start.ps1 -NoBrowser`。

也可以通过根目录的 Python 启动文件运行（自动使用项目虚拟环境）：

```powershell
python run.py
# 不自动打开浏览器
python run.py --no-browser
```

换到新环境时先安装 Python 3.11～3.13、Node.js 22（建议安装 uv），再运行：

```powershell
.\setup.ps1
.\start.ps1
```

安装阶段需要下载依赖；应用运行阶段没有在线 AI、云服务、远程字体或模型下载。安装脚本默认优先使用现有 Edge/Chrome，找不到时安装项目内的 Chromium headless shell。若准备独立离线运行时，可执行 `.\setup.ps1 -BundleBrowser` 提前下载浏览器。Python 依赖和 OCR 模型必须提前安装；此版本尚未制作无需 Python/Node 的安装包。

若本机 PowerShell 执行策略禁止脚本，可从本目录使用 `powershell -ExecutionPolicy Bypass -File .\start.ps1`，仅影响该脚本进程。

## 使用

1. 点击「导入简历模板」选择 PDF、JPG、PNG、WebP；也可以拖入文件。点击「体验示例」打开两页合成简历。
2. 左侧是原始参考，右侧是真实的文本、线条、矩形和图片占位框。原生 PDF 提取文字和图形；图片/扫描 PDF 使用本地 OCR，需人工校对。
3. 单击选择元素，双击文字直接编辑；右侧可修改文字内容、位置、尺寸、字号、字宽、颜色、字重、行高和对齐方式。删除文字内容可以保留空文字框。
4. 拖动元素或八个尺寸手柄。左侧工具栏可绘制文字、图片区域、矩形和线条。
5. 截图中的头像未自动定位时，选择「框选图片区」，在左侧原页拖出矩形或椭圆区域。新占位框不会自动删除重叠的 OCR 文字；右侧会提示你人工检查。
6. 选择图片区，在属性栏上传自己的 JPG/PNG/WebP。可以切换矩形、圆形/椭圆、圆角、cover/contain，调整缩放与水平/垂直裁剪定位；清除图片会保留框。
7. 点击「保存」写入本地工程；首页可打开最近工程。导出 `.rresume` 工程包便于备份、迁移和重新打开，勾选是否包含原始参考。
8. 导出 PDF 或独立 HTML。未替换图片区会提示，确认后保留背景和边框，不输出「上传图片」文字。导出会先保存当前修改。

快捷键：V 选择、T 文字、I 图片、R 矩形、L 线条；Ctrl+S 保存、Ctrl+Z 撤销、Ctrl+Y / Ctrl+Shift+Z 重做、Ctrl+D 复制、Ctrl+C / Ctrl+V 复制粘贴所选对象、Delete 删除、方向键微移，Shift+方向键移动 10 个页面单位。文本输入框中保留正常的文字编辑快捷键。

## 隐私与数据

- 导入默认保留原文，修改直接更新 `Element.text`，没有原图底图、白色遮罩或旧文本覆盖层。
- PDF 源图片只读取显示位置，不解码到素材库；整页扫描图进入 OCR 路径，不生成整页头像框。
- 原始页面会渲染到 `reference/` 供对照，可能含原个人信息。点击原始参考面板的删除按钮可永久清除参考，同时清空撤销历史。
- `assets/` 只接收用户主动上传的新图片；图片重新编码为 PNG，保留透明度、应用 EXIF 方向并剥离元数据。
- PDF/HTML 只读取当前元素与引用的新图片，不包含原始参考、撤销历史或未引用的图片。
- 成品标题使用固定「简历」，不把来源文件名写入 HTML/PDF 元数据；工程包仍保留你当前设置的工程名称。
- 撤销历史只在当前浏览器页面的内存中；解析提示面板提供「清空撤销历史」。保存与工程导出不持久化历史。
- 导出工程包可取消原始参考。工程包包含当前 JSON 与已引用的新图片；重新导入会分配新工程 ID。
- 文件上限 25MB，图片上限 3000 万像素，最多 20 页；项目包解压总量上限 100MB。路径穿越、重复路径、非法文件、非法资源和颜色/字体注入会被拒绝。
- 源文件解析在独立进程执行，超时 180 秒；错误导入不会覆盖已有工程。数据目录可通过 `RESUME_DATA_DIR` 配置，浏览器路径可通过 `RESUME_BROWSER_PATH` 配置。

## 当前边界

已覆盖 M0～M4 的基础工作流。复杂 PDF 裁剪、曲线、遮罩、缺失字体仍需人工校正；OCR 的颜色、字体和布局估计不是精确恢复。PDF 原字体名称会保留为线索，使用系统后备字体，并估计字宽以保持原行边界；换机器后应再次检查排版。

文字增长会提示当前页溢出及越界，不自动移动相邻对象或跨页重排。导出前请逐页检查；溢出文字不在元素边界静默裁切，但越过页面边缘的部分仍会按纸张边界裁切。

P1 的自动候选图片区检测、多选对齐、吸附、差异叠加、批量清空、段落流式排版和安装包尚未实现。源头像的复杂圆形裁剪由用户在属性栏手动校正。

## 开发与验证

```powershell
# 后端开发
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload
# 新终端中启动前端开发服务器
cd frontend
npm run dev
```

前端开发地址为 `127.0.0.1:5173`，API 通过 Vite 代理到 8765。正式启动使用已经构建的 `frontend/dist/`，无需 npm 运行。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 先启动本地服务，再执行真实浏览器验收
.\.venv\Scripts\python.exe scripts/verify_ui.py
.\.venv\Scripts\python.exe scripts/check_runtime.py
cd frontend
npm run build
```

测试样例均为自行生成的虚构内容：`examples/native-resume.pdf`（两页原生 PDF + 合成头像）、`chinese-resume.png`（中文截图）、`scanned-resume.pdf`（整页扫描）、`repeated-photo.pdf`（同一图像资源多位置）。生成脚本为 `scripts/create_samples.py`。这些样例可以自由用于本项目的验收。

真实浏览器脚本验证编辑、撤销、拖动、图片上传/裁剪、工程重开、手动区域、溢出与分页，并检查导出的 PDF；截图和导出测试文件保存在忽略版本管理的 `artifacts/`。网络验证是禁止 OCR 网络调用、阻断导出页面网络请求、检查前端外部请求；尚未进行操作系统断网开关的人工测试。

API 文档：<http://127.0.0.1:8765/api/docs>。数据模型：`backend/models.py` 与 `frontend/src/types.ts`。实现与验收记录见 [docs/开发进度.md](docs/开发进度.md)，依赖与模型声明见 [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。
