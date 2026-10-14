# 第三方依赖与模型记录

Python 全量锁定为 `uv.lock` 与 `requirements.lock`；前端锁定为 `frontend/package-lock.json`。本次安装环境为 Windows x64 / Python 3.13 / Node 22。

| 核心组件 | 本次版本 | 许可与离线说明 |
|---|---|---|
| FastAPI / Uvicorn | 0.143.0 / 0.54.0 | MIT / BSD；本机 API |
| pdfplumber / pdfminer.six | 0.11.10 / 20260107 | MIT；本地对象解析 |
| pypdfium2 / PDFium | 5.14.0 | Apache-2.0 / BSD-3-Clause 及依赖声明；本地渲染 |
| RapidOCR | 3.10.0 | Apache-2.0；所选模型已随 wheel 安装 |
| ONNX Runtime | 1.31.0 | MIT；CPU 本地推理 |
| Pillow | 12.3.0 | MIT-CMU；图片校验/正规化 |
| OpenCV headless | 5.0.0.93 | Apache-2.0 及其第三方声明；RapidOCR 间接依赖 |
| Playwright | 1.63.0 | Apache-2.0；PDF 导出使用本地 Chromium 或现有 Edge/Chrome |
| React / TypeScript / Vite | 19 / 5.7 / 6.4（精确版见 npm 锁） | MIT / Apache-2.0 / MIT；前端全部构建到本机，不使用 CDN |

完整直接/间接依赖的版本与安装包许可字段见 `dependencies.json`；原文副本在 `licenses/`。可运行 `scripts/collect_notices.py` 为更新后的锁定环境重新收集。表格用于开发追踪；若分发完整可执行安装包，应按最终打包的每一项资源重新核对和附带通知。

## OCR 模型

采用 RapidOCR 3.10.0 wheel 中的三个默认 ONNX 模型，显式提供本地路径；应用运行期间不触发模型下载。来源、版权和再分发条件保留在 [RapidOCR MODEL_LICENSES.md](licenses/rapidocr/licenses/MODEL_LICENSES.md) 及其 [Apache 2.0 许可](licenses/rapidocr/licenses/LICENSE)。上游权重归 Baidu/PaddleOCR 相关权利人，RapidOCR 负责转换/包装。

| 模型文件 | 体积 | SHA-256 |
|---|---:|---|
| PP-OCRv6_det_small.onnx | 9,929,594 B | `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` |
| ch_ppocr_mobile_v2.0_cls_mobile.onnx | 585,532 B | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |
| PP-OCRv6_rec_small.onnx | 21,234,383 B | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |

`scripts/check_runtime.py` 校验本地运行环境，并写出 `runtime/models.json`。模型总量约 30.3 MiB；RapidOCR wheel 下载约 26 MiB，ONNX Runtime wheel 约 14 MiB，OpenCV wheel 约 42 MiB。最终安装体积受平台与间接依赖影响，以打包产物为准。

浏览器下载可达百余 MiB；本机已有 Edge 已通过导出验收。`setup.ps1 -BundleBrowser` 安装 Chromium headless shell 到项目 `runtime/browsers/`，不修改系统浏览器。Microsoft Edge / Google Chrome 是系统外部依赖，本项目没有复制或再分发它们。若分发 Chromium 运行时，需附带其随运行时提供的第三方通知。

字体采用系统字体回退（微软雅黑、宋体、Arial、Georgia 等），项目没有复制或打包字体文件。跨平台需要预装具有适当授权的中文字体。合成截图样例只包含绘制的图像像素，不包含字体文件。

技术依据：[pdfplumber 官方仓库](https://github.com/jsvine/pdfplumber)、[pypdfium2 官方仓库](https://github.com/pypdfium2-team/pypdfium2)、[RapidOCR 官方仓库](https://github.com/RapidAI/RapidOCR)、[Playwright 官方 PDF API](https://playwright.dev/python/docs/api/class-page#page-pdf)。实现依据当前锁定环境实测，不依赖未来版本的接口保证。
