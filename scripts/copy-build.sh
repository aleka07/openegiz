#!/bin/bash
# Копирует 4 файла Unity WebGL билда из указанного пути в ./build/
# Ищет файлы по расширениям: .data, .framework.js, .loader.js, .wasm
# Использование: bash scripts/copy-build.sh /путь/к/папке/с/билдом

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Использование: $0 <путь_к_папке_с_билдом>"
    echo "  Папка (или подпапка Build/) должна содержать файлы с расширениями:"
    echo "    *.data  *.framework.js  *.loader.js  *.wasm"
    exit 1
fi

SRC_DIR="$1"
DEST_DIR="./build"

# Если в SRC_DIR есть подпапка Build/, используем её
if [ -d "$SRC_DIR/Build" ]; then
    SRC_DIR="$SRC_DIR/Build"
    echo "Найдена подпапка Build/, используем: $SRC_DIR"
fi

EXTENSIONS=("*.data" "*.framework.js" "*.loader.js" "*.wasm")

# Ищем файлы по расширениям
FOUND=()
for ext in "${EXTENSIONS[@]}"; do
    match=$(find "$SRC_DIR" -maxdepth 1 -name "$ext" -type f 2>/dev/null | head -1)
    if [ -z "$match" ]; then
        echo "ОШИБКА: Файл с расширением '$ext' не найден в $SRC_DIR"
        exit 1
    fi
    FOUND+=("$match")
done

# Создаём папку build если её нет, очищаем старые файлы
mkdir -p "$DEST_DIR"
rm -f "$DEST_DIR"/*.data "$DEST_DIR"/*.framework.js "$DEST_DIR"/*.loader.js "$DEST_DIR"/*.wasm
echo "Старые файлы в $DEST_DIR очищены"

# Копируем файлы
echo "Копирование файлов из $SRC_DIR в $DEST_DIR ..."
for f in "${FOUND[@]}"; do
    name=$(basename "$f")
    echo "  $name"
    cp "$f" "$DEST_DIR/$name"
done

echo ""
echo "Готово! ${#FOUND[@]} файлов скопировано в $DEST_DIR"
