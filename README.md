# 鳄鱼骑行日 · Croc & Cycle

一个完整的单文件网页：绿色鳄鱼骑着珊瑚橙色自行车，沿河岸慢慢前进。插画、样式、SVG 动画和暂停按钮都包含在 `index.html` 中。打开网页即可播放，无需下载图片、字体或 JavaScript 库。

网页保留标题 **“骑着风，慢慢来。”**。项目同时提供 HTML 生成器和可重复运行的 MP4 导出脚本。

## 直接打开网页

用支持 SVG 声明式动画的浏览器打开 `index.html`。也可以在项目根目录运行一个本地静态服务：

```bash
python -m http.server 8000
```

然后打开 `http://localhost:8000`。这一步只需要 Python 标准库；直接打开 HTML 则不需要 Python。

网页包含以下运动与交互：

- 双轮通过 `animateTransform` 持续旋转，单圈周期为 1.2 秒。
- 双腿、踏板、曲柄共用 2.4 秒的时间轴，两侧踏板相差半圈。
- 肩部和髋部跟随身体轻摆，双手保持在车把位置，脚部跟随踏板。
- 云、路面标记和微风线条随时间运动。
- 暂停 / 继续按钮控制 SVG 时间轴；页面会读取系统的减少动态效果偏好。

动画本身由 SVG 驱动。页面内的 JavaScript 只负责交互控制。

## 源码结构

| 文件 | 作用 |
| --- | --- |
| `index.html` | 可直接打开或托管的完整网页。保留交付版本的原始字节。 |
| `scripts/build_html.py` | 原始几何与 HTML 模板，计算关节位置和 32 段线性关键帧，再生成网页。 |
| `scripts/sample_frames.py` | 从 HTML 读取 SVG，对当前项目的动画离线插值，生成静态 SVG 帧和清单。 |
| `scripts/render_video.cjs` | 使用 Sharp 渲染静态帧，并将 PNG 帧传入 FFmpeg 编码。 |
| `package.json` | Node.js 依赖及常用脚本。Sharp 固定为 `0.35.5`。 |
| `requirements.txt` | 视频采样所需的 Python 依赖：`lxml==6.1.1`。 |
| `.gitignore` | 排除生成产物、虚拟环境、缓存与 `node_modules`。 |
| `.gitattributes` | 将文本文件的行尾设为 LF，将 PNG / MP4 设为二进制。 |

生成的帧、预览图片和视频放在 `build/`，不作为源码提交。

## 重新生成 HTML

HTML 生成器仅使用 Python 标准库：

```bash
python scripts/build_html.py
```

检查当前 HTML 是否与生成器逐字节一致，不写入文件：

```bash
python scripts/build_html.py --check
```

也可以指定输出文件：

```bash
python scripts/build_html.py --output build/regenerated.html
```

如果修改插画或动画，建议修改 `scripts/build_html.py` 后重新生成 `index.html`，避免模板与交付网页不一致。脚本的相对路径以仓库根目录为基准，不依赖调用时的工作目录。

## 导出 MP4

### 运行环境

视频导出需要：

- Python 3.10 或更新版本。
- Node.js 20.9 或更新版本，以及 npm。
- FFmpeg，且构建中包含 `libx264` 编码器。默认从 `PATH` 查找 `ffmpeg`。
- 可显示中文的系统字体。默认字体列表包含 Noto Sans CJK SC、思源黑体、苹方和微软雅黑，最后回退到 `sans-serif`。

字体没有打包进仓库。不同系统的字体回退与字形可能不同；缺少中文字库时，视频标题可能出现缺字。可以通过采样器的 `--font-family` 指定已安装的字体。

下面的命令假定 `python` 指向所需的 Python 版本。某些系统需要用 `python3` 替换它；也可以先激活自己的 Python 虚拟环境。

### 安装依赖并生成

在项目根目录执行：

```bash
python -m pip install -r requirements.txt
npm install
npm run video
```

默认输出为 `build/crocodile-cycling.mp4`：

| 参数 | 默认值 |
| --- | --- |
| 画面 | 1920 × 1080，16:9 |
| 帧率 | 30 fps |
| 时长 | 12 秒 |
| 帧数 | 360 |
| 视频编码 | H.264，`libx264` |
| 像素格式 | `yuv420p` |
| 质量 | CRF 18，medium preset |
| 音频 | 无 |

也可以分开运行两个步骤：

```bash
python scripts/sample_frames.py
node scripts/render_video.cjs
```

第一步生成 `build/frames/frame-000000.svg` 等静态帧和 `manifest.json`。第二步根据清单的尺寸、帧率和帧数编码，不需要把所有 PNG 帧同时存到磁盘。

### 动画与视频的对应关系

Sharp 渲染静态 SVG；采样脚本先把每一时刻的 `animate` / `animateTransform` 求值到父元素属性，再移除动画节点。它处理本项目所用的线性路径插值、平移、旋转和透明度，共 15 个动画节点。

所有采样与视频排版都发生在解析后的副本中，`index.html` 不会被改写。网页中原本为 18 秒和 22 秒的两条云动画，在采样副本中统一使用 12 秒周期；骑行的 2.4 秒周期和车轮的 1.2 秒周期保持原样。因此默认导出的画面能在 12 秒处回到起始状态。清单里的 `loop_at_duration` 记录完整帧在起点和周期终点是否相同；360 个实际视频帧取样于 `0/30` 至 `359/30` 秒，不额外重复终点帧。

导出画面沿用同版的插画、中文主标题、副标题和文案，并以固定 SVG 文字位置构成 16:9 画面。它不是浏览器整页录像，因此网页的响应式 CSS、按钮与浏览器字体排版不会原样录入视频。

采样器面向此项目实际使用的动画，不是通用 SMIL 实现。它会拒绝不支持的动画类型或插值模式。若新增复杂动画，需要同时扩展采样器。

### 常用参数

生成较小的 16:9 视频：

```bash
python scripts/sample_frames.py --width 1280 --height 720
node scripts/render_video.cjs --output build/crocodile-720p.mp4
```

只编码已有帧的前 12 帧，快速检查依赖与编码链路：

```bash
node scripts/render_video.cjs --limit 12 --output build/smoke.mp4
```

指定其他输出目录、字体、FFmpeg 程序或编码质量：

```bash
python scripts/sample_frames.py --output build/custom-frames --font-family "Noto Sans CJK SC, sans-serif"
node scripts/render_video.cjs --frames build/custom-frames --output build/custom.mp4 --ffmpeg ffmpeg --crf 18 --preset medium
```

采样器也接受 `--input`、`--duration`、`--fps` 和 `--cloud-period`。时长乘帧率必须得到整数帧数，宽高必须为正偶数。更改周期或时长后，应查看清单中的 `loop_at_duration`，不能默认仍然循环衔接。

编码器默认加载 `require('sharp')`。需要复用已安装模块做本地验证时，可以可选地设置 `SHARP_MODULE_PATH`；正常安装项目依赖后不需要它。`FFMPEG_PATH` 可以指定 FFmpeg 程序，也可以使用 `--ffmpeg` 参数。

完整参数说明：

```bash
python scripts/sample_frames.py --help
node scripts/render_video.cjs --help
```

## 本次实际验证

下列结果在准备仓库时已经完成：

- 原交付 HTML 以原始字节复制为 `index.html`，共 35,778 字节。
- `python scripts/build_html.py --check` 通过，生成器输出与 `index.html` 逐字节相同。
- 默认采样成功生成 360 帧，覆盖 15 个动画节点，0 秒与 12 秒的完整静态 SVG 内容相同。
- 已用 Sharp 渲染首帧，并目视检查中文标题、鳄鱼、自行车和版面。
- 已完成 12 帧、1920 × 1080 的短视频编码。
- 已完成全部 360 帧的正式编码。FFprobe 读取的结果为 H.264 High、1920 × 1080、`yuv420p`、30 fps、12.000000 秒、360 帧。
- Node.js 对 `scripts/render_video.cjs` 的语法检查通过。

本次验证使用现有运行环境中的 Node.js 24.22.3、Sharp 0.35.5、lxml 6.1.1 和 FFmpeg 7.1.5。

尚未在全新机器上执行依赖安装，也未单独验证 Windows、macOS、其他字体环境或各浏览器版本的播放表现。没有生成 `package-lock.json`，因此当前只锁定直接依赖 Sharp 的版本，未锁定完整的 npm 间接依赖树。实际显示可能受字体和渲染库版本影响。
