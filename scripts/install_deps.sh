#!/usr/bin/env bash
# 在 Linux 板子上安装依赖（支持在线与离线两种方式）
#
# 用法:
#   在线安装（板子能联网）:
#       ./scripts/install_deps.sh
#   离线安装（先在电脑上下载包，拷到板子）:
#       1. 在电脑上:  ./scripts/install_deps.sh --download-only ./offline
#       2. 把 ./offline 目录拷到板子
#       3. 在板子上:  ./scripts/install_deps.sh --offline-dir ./offline
#   只装 Python 包（跳过 apt 系统包）:
#       ./scripts/install_deps.sh --pip-only
set -euo pipefail

# ---------- 参数解析 ----------
DOWNLOAD_ONLY=0
OFFLINE_DIR=""
PIP_ONLY=0
ARCHS=""       # 空=当前架构；all=全部Linux架构；或逗号分隔如 "aarch64,x86_64"
while [ $# -gt 0 ]; do
    case "$1" in
        --download-only)
            DOWNLOAD_ONLY=1
            ;;
        --offline-dir)
            if [ $# -ge 2 ]; then
                OFFLINE_DIR="$2"; shift
            else
                echo "--offline-dir 需要参数" >&2
                exit 1
            fi
            ;;
        --offline-dir=*)
            OFFLINE_DIR="${1#*=}"
            ;;
        --pip-only)
            PIP_ONLY=1
            ;;
        --arch)
            if [ $# -ge 2 ]; then
                ARCHS="$2"; shift
            else
                echo "--arch 需要参数: aarch64|x86_64|all" >&2
                exit 1
            fi
            ;;
        --arch=*)
            ARCHS="${1#*=}"
            ;;
        *)
            echo "未知参数: $1" >&2
            echo "用法: $0 [--download-only] [--arch aarch64|x86_64|all] [--offline-dir 目录] [--pip-only]" >&2
            exit 1 ;;
    esac
    shift
done

# 项目根目录
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT/.venv"
PY_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

# ---------- 平台 / 架构检测 ----------
ARCH_NOW="$(uname -m)"
# 把架构名归一化
normalize_arch() {
    case "$1" in
        amd64) echo "x86_64" ;;
        arm64) echo "aarch64" ;;
        *) echo "$1" ;;
    esac
}
# arch -> pip platform tag
arch_to_plat() {
    case "$1" in
        x86_64) echo "manylinux2014_x86_64" ;;
        aarch64) echo "manylinux2014_aarch64" ;;
        *) echo "" ;;
    esac
}

if [ -n "$ARCHS" ]; then
    if [ "$ARCHS" = "all" ]; then
        # 拉全部 Linux 架构（覆盖 arm 与 x86_64 板子）
        TARGET_ARCHS="x86_64 aarch64"
    else
        # 逗号分隔或单架构
        TARGET_ARCHS="$(echo "$ARCHS" | tr ',' ' ')"
    fi
else
    # 默认：只处理当前机器架构
    TARGET_ARCHS="$(normalize_arch "$ARCH_NOW")"
fi

# 用于本机安装时的架构标记（armv7 提示等）
ARCH="$(normalize_arch "$ARCH_NOW")"
PLAT_WHEEL="$(arch_to_plat "$ARCH")"
echo "==> Platform: $(uname -s)  Arch: $ARCH  (target: $TARGET_ARCHS)"
case "$ARCH" in
    armv7l|armv6l)
        echo "!! Warning: $ARCH is old; sherpa-onnx may need source build" >&2
        ;;
esac

# ---------- Python 版本检测 ----------
if command -v python3 >/dev/null 2>&1; then
    PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo unknown)"
else
    PY_VERSION="not found"
fi
echo "==> 检测到 python3: $PY_VERSION"
case "$PY_VERSION" in
    3.1[0-9]|3.9|3.8)
        echo "   OK: 满足要求 (>=3.8)" ;;
    *)
        echo "!! 需要 python3 >= 3.8，当前: $PY_VERSION" >&2
        echo "   请先安装 python3（Debian: sudo apt install python3 python3-venv python3-pip）" >&2
        [ "$DOWNLOAD_ONLY" = 1 ] || exit 1 ;;
esac

# ---------- 系统包（apt） ----------
if [ "$PIP_ONLY" = 0 ] && [ "$DOWNLOAD_ONLY" = 0 ]; then
    echo "==> 系统包（apt）"
    sudo apt-get update

    # 注意：不装 ffmpeg —— mpv 自带 ffmpeg 解码库，播放无需系统 ffmpeg；
    # 且部分板厂镜像的 trim 包占用 /usr/bin/ffmpeg 会造成 dpkg 冲突。
    # 仅开发期生成测试音频才需要 ffmpeg（可选，见 scripts/gen_test_audio.sh）。
    sudo apt-get install -y python3 python3-pip python3-venv \
        mpv alsa-utils libportaudio2 libffi-dev

    # 音频用户组：把当前用户加入 audio 组（ALSA 权限）
    if ! groups | grep -qw audio; then
        echo "==> 把当前用户加入 audio 组（需重新登录生效）"
        sudo usermod -a -G audio "$USER"
    fi
elif [ "$DOWNLOAD_ONLY" = 1 ]; then
    echo "==> 下载模式：跳过 apt 安装（板子上执行时再装）"
fi

# ---------- 创建虚拟环境 ----------
if [ "$DOWNLOAD_ONLY" = 0 ]; then
    echo "==> 创建虚拟环境 $VENV_DIR"
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
    fi
fi

# ---------- Python packages ----------
if [ "$DOWNLOAD_ONLY" = 1 ]; then
    # On dev machine: download ALL wheels for the target arch(s) + python version,
    # so any board can install offline with no missing deps.
    #
    #   TARGET_PY 板子上的 python 版本（默认 3.11；可 TARGET_PY=3.10 覆盖）
    DEST="${OFFLINE_DIR:-./offline}"
    TARGET_PY="${TARGET_PY:-3.11}"
    mkdir -p "$DEST"
    echo "==> Downloading wheels: arch(s)=$TARGET_ARCHS python=$TARGET_PY -> $DEST"
    PY_TAG="cp${TARGET_PY//.}"
    # 为每个目标架构拉取带编译的包
    for ta in $TARGET_ARCHS; do
        tp="$(arch_to_plat "$ta")"
        if [ -z "$tp" ]; then
            echo "   !! 跳过不支持的架构: $ta" >&2
            continue
        fi
        echo "   -- arch=$ta (platform=$tp)"
        python3 -m pip download -r "$ROOT/requirements.txt" \
            --platform "$tp" --python-version "$TARGET_PY" \
            --implementation cp --abi "${PY_TAG}" \
            --only-binary=:all: -d "$DEST" || true
    done
    # 纯 Python 包（pypinyin/pyyaml/sounddevice）兜底（不限平台）
    python3 -m pip download -r "$ROOT/requirements.txt" \
        --no-deps --only-binary=:all: -d "$DEST" || true
    echo "==> Done. Copy '$DEST' to the board, then run:"
    echo "    ./scripts/install_deps.sh --offline-dir=$DEST"
    exit 0
fi

echo "==> Python 包（pip）"
if [ -n "$OFFLINE_DIR" ]; then
    echo "   离线安装自 $OFFLINE_DIR"
    "$PIP_BIN" install --no-index --find-links="$OFFLINE_DIR" -r "$ROOT/requirements.txt"
elif command -v pip3 >/dev/null 2>&1; then
    "$PIP_BIN" install -r "$ROOT/requirements.txt"
else
    "$VENV_DIR/bin/python" -m pip install -r "$ROOT/requirements.txt"
fi

# ---------- 验证 ----------
echo "==> 验证依赖"
"$PY_BIN" -c "import numpy, yaml, pypinyin" && echo "   numpy/pyyaml/pypinyin OK"
if "$PY_BIN" -c "import sherpa_onnx" 2>/dev/null; then
    echo "   sherpa-onnx OK"
else
    echo "!! sherpa-onnx 未安装成功" >&2
    if [ -z "$PLAT_WHEEL" ]; then
        echo "   你的架构 $ARCH 可能没有官方 wheel，需从源码编译 sherpa-onnx：" >&2
        echo "   https://k2-fsa.github.io/sherpa/onnx/install/wheel.html" >&2
    fi
fi

# ---------- 模型提示 ----------
echo "==> 模型"
if [ -d "$ROOT/models/asr" ] && [ -d "$ROOT/models/kws" ]; then
    echo "   models/asr、models/kws 已存在"
    echo "   models/tts_melo 用于离线播报（可选）："
    echo "   https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2"
else
    echo "   尚未下载模型，请参考 models/README.md 下载 ASR/KWS 模型到 models/"
fi

echo "==> 完成。启动方式："
echo "   $PY_BIN $ROOT/app/main.py --voice"

