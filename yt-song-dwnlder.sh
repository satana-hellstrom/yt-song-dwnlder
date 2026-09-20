#!/usr/bin/env bash
#
# yt-song-dwnlder — a terminal music downloader TUI in pure bash + yt-dlp
#
# Flow:
#   * type a song name (or paste a URL) in the boxed field at the top
#   * move up/down with arrow keys to pick container / quality / folder
#   * press Enter on < Search & Download >
#   * pick a song from the results list (arrows), Enter downloads it,
#     q goes back to the search page
#
# Requirements: bash 4+, yt-dlp (pip install yt-dlp), ffmpeg
# Usage:       ./yt-song-dwnlder.sh
#

set -u

# ----------------------------- config ----------------------------------------
CONFIG_DIR="$HOME/.config/yt-song-dwnlder"
CONFIG_FILE="$CONFIG_DIR/config.sh"

download_dir="$HOME/Music"
container="mp3"
quality="320k"
embed_metadata=1
embed_thumbnail=1

mkdir -p "$CONFIG_DIR" 2>/dev/null
# shellcheck disable=SC1090
[[ -f "$CONFIG_FILE" ]] && . "$CONFIG_FILE"

save_config() {
  {
    printf 'download_dir=%q\n'   "$download_dir"
    printf 'container=%q\n'       "$container"
    printf 'quality=%q\n'         "$quality"
    printf 'embed_metadata=%q\n'  "$embed_metadata"
    printf 'embed_thumbnail=%q\n' "$embed_thumbnail"
  } > "$CONFIG_FILE"
}

# ----------------------------- containers ------------------------------------
CONTAINER_LABELS=( "MP3"     "M4A/AAC" "Opus"  "FLAC"  "WAV" "OGG" "Best" )
CONTAINER_FMTS=(    "mp3"     "m4a"     "opus"  "flac"  "wav" "ogg" "best" )
CONTAINER_DESCS=(  "universal lossy .mp3"  "apple .m4a (aac)"
                   "youtube native .opus"  "lossless .flac"
                   "uncompressed .wav"     ".ogg vorbis"
                   "keep original stream" )
QUALITIES=( "best" "320k" "256k" "192k" "128k" )

container_label() {
  local i
  for i in "${!CONTAINER_FMTS[@]}"; do
    if [[ ${CONTAINER_FMTS[i]} == "$container" ]]; then
      printf '%s' "${CONTAINER_LABELS[i]}"
      return
    fi
  done
  printf '%s' "${CONTAINER_LABELS[0]}"
}

# ----------------------------- terminal helpers ------------------------------
ESC=$'\033'
UP=$'\033[A'; DOWN=$'\033[B'; RIGHT=$'\033[C'; LEFT=$'\033[D'
ENTER=''      # read -rsn1 gives an empty string for Enter
TAB=$'\t'
BS=$'\x7f'

hide_cursor()  { printf '%s[?25l'  "$ESC"; }
show_cursor()  { printf '%s[?25h'  "$ESC"; }
alt_screen_on(){ printf '%s[?1049h' "$ESC"; }
alt_screen_off(){ printf '%s[?1049l' "$ESC"; }
clear_screen() { printf '%s[2J%s[H' "$ESC" "$ESC"; }
move()         { printf '%s[%d;%dH' "$ESC" "$1" "$2"; }

read_key() {
  IFS= read -rsn1 key || exit 0   # EOF on stdin -> quit cleanly
  if [[ $key == "$ESC" ]]; then
    if IFS= read -rsn2 -t 0.002 seq 2>/dev/null; then
      key+="$seq"
    fi
  fi
}

on_exit() { show_cursor; alt_screen_off; }
trap on_exit EXIT
trap 'on_exit; exit 130' INT TERM

# ----------------------------- form widgets -----------------------------------
# rows: 0 entry   1 container   2 quality   3 folder   4 meta   5 thumb   6 sep   7 go
ROWS=8
SEP=6
sel=0 text="" tcur=0 fcur=0 status=""

move_sel() {  # $1 = +1 / -1
  local d=$1
  sel=$(( (sel + d + ROWS) % ROWS ))
  while (( sel == SEP )); do
    sel=$(( (sel + d + ROWS) % ROWS ))
  done
}

print_row() {  # $1 line  $2 label  $3 value  $4 focused(0/1)
  local line=$1 label=$2 value=$3 focused=$4
  move "$line" 3
  if (( focused )); then
    printf '%s[7m> %-16s%s[27m' "$ESC" "$label" "$ESC"
  else
    printf '  %-16s' "$label"
  fi
  printf ' %s' "$value"
}

draw_box_row() {  # $1 line  $2 label  $3 buf  $4 cursor  $5 focused(0/1)
  local line=$1 label=$2 buf=$3 cur=$4 focused=$5
  local boxw=46 start=0 i ch
  if (( ${#buf} >= boxw )); then
    start=$(( cur - boxw + 2 ))
    (( start < 0 )) && start=0
  fi
  move "$line" 3
  if (( focused )); then
    printf '%s[7m> %-16s%s[27m' "$ESC" "$label" "$ESC"
  else
    printf '  %-16s' "$label"
  fi
  move "$line" 22
  printf '['
  for (( i = 0; i < boxw; i++ )); do
    ch=${buf:$(( start + i )):1}
    [[ -z $ch ]] && ch=' '
    if (( focused && start + i == cur )); then
      printf '%s[7m%s%s[27m' "$ESC" "$ch" "$ESC"
    else
      printf '%s' "$ch"
    fi
  done
  printf ']'
}

draw_form() {
  clear_screen
  move 1 6
  printf '%s[1;32m~ yt-song-dwnlder ~ terminal music downloader%s[0m' "$ESC" "$ESC"
  move 2 3
  printf '%s[2msettings: %s%s[0m' "$ESC" "$CONFIG_FILE" "$ESC"

  draw_box_row 4 "Song name / URL" "$text" "$tcur" "$(( sel == 0 ? 1 : 0 ))"
  print_row 5 "Container" "$(container_label)" "$(( sel == 1 ? 1 : 0 ))"
  print_row 6 "Quality" "$quality" "$(( sel == 2 ? 1 : 0 ))"
  draw_box_row 7 "Save folder" "$download_dir" "$fcur" "$(( sel == 3 ? 1 : 0 ))"
  local meta_v thumb_v
  if (( embed_metadata ));  then meta_v="[x] yes";  else meta_v="[ ] no"; fi
  if (( embed_thumbnail )); then thumb_v="[x] yes"; else thumb_v="[ ] no"; fi
  print_row 8 "Embed metadata"   "$meta_v"  "$(( sel == 4 ? 1 : 0 ))"
  print_row 9 "Embed thumbnail" "$thumb_v" "$(( sel == 5 ? 1 : 0 ))"

  move 10 3
  printf '%s[2m----------------------------------------%s[0m' "$ESC" "$ESC"

  move 11 22
  if (( sel == 7 )); then
    printf '%s[7m < Search & Download > %s[27m' "$ESC" "$ESC"
  else
    printf '%s[1;32m < Search & Download > %s[0m' "$ESC" "$ESC"
  fi

  if [[ -n $status ]]; then
    move 13 3
    printf '%s[1;31m%s%s[0m' "$ESC" "${status:0:74}" "$ESC"
  fi
  move 15 3
  if (( sel == 0 || sel == 3 )); then
    printf '%s[2mtype to edit   Down/Tab next field   Esc quit%s[0m' "$ESC" "$ESC"
  else
    printf '%s[2mup/down move   Enter select   q quit%s[0m' "$ESC" "$ESC"
  fi
}

# edit keys for the two boxed fields (entry / folder)
# $1 = name of buffer var, $2 = name of cursor var
handle_edit_keys() {
  local -n buf=$1 cur=$2
  case "$key" in
    "$DOWN" | "$TAB" | "$ENTER" ) move_sel 1 ;;
    "$UP" )                        move_sel -1 ;;
    "$LEFT" )  (( cur > 0 )) && (( cur-- )) ;;
    "$RIGHT" ) (( cur < ${#buf} )) && (( cur++ )) ;;
    "$BS" )    if (( cur > 0 )); then
                 buf="${buf:0:cur-1}${buf:cur}"
                 (( cur-- ))
               fi ;;
    "$ESC" )   exit 0 ;;
    * )        if [[ $key =~ ^[[:print:]]$ ]]; then
                 buf="${buf:0:cur}$key${buf:cur}"
                 (( cur++ ))
               fi ;;
  esac
}

# ----------------------------- list picker -----------------------------------
# $1 title, $2 items array name, $3 starting index, $4 footer (optional)
# sets REPLY=index and returns 0 on Enter; returns 1 on q/Esc
pick_list() {
  local title=$1
  local -n _items=$2
  local sel=${3:-0}
  local footer=${4:-"up/down select   Enter confirm   q back"}
  local n=${#_items[@]} i
  (( n == 0 )) && return 1
  while :; do
    clear_screen
    move 2 3
    printf '%s[1m %s %s[0m' "$ESC" "$title" "$ESC"
    for (( i = 0; i < n; i++ )); do
      move $(( i + 5 )) 5
      if (( i == sel )); then
        printf '%s[7m> %s%s[27m' "$ESC" "${_items[i]}" "$ESC"
      else
        printf '  %s' "${_items[i]}"
      fi
    done
    move $(( n + 7 )) 5
    printf '%s[2m%s%s[0m' "$ESC" "$footer" "$ESC"
    read_key
    case "$key" in
      "$UP" | k )    sel=$(( (sel - 1 + n) % n )) ;;
      "$DOWN" | j )  sel=$(( (sel + 1) % n )) ;;
      "$ENTER" )     REPLY=$sel; return 0 ;;
      "$ESC" | q )   return 1 ;;
    esac
  done
}

# ----------------------------- download --------------------------------------
draw_bar() {  # $1 line  $2 pct  $3 width
  local line=$1 pct=$2 w=$3
  local pint=${pct%%.*}
  [[ $pint =~ ^[0-9]+$ ]] || pint=0
  (( pint > 100 )) && pint=100
  local filled=$(( w * pint / 100 ))
  move "$line" 3
  printf '['
  printf '%*s' "$filled" ''  | tr ' ' '#'
  printf '%*s' "$(( w - filled ))" '' | tr ' ' '-'
  printf '] %s%%' "$pct"
}

run_download() {  # $1 url ; result message in REPLY
  local url=$1
  local dir=${download_dir/#\~/$HOME}
  mkdir -p "$dir" 2>/dev/null

  local -a cmd=( yt-dlp --no-playlist -x
                 --audio-format "$container"
                 --newline
                 --progress-template 'download:%(progress._percent_str)s'
                 --print 'after_move:SAVED:%(filepath)s'
                 -o "$dir/%(title)s.%(ext)s" )
  if [[ $quality != best && $container != best && $container != flac && $container != wav ]]; then
    cmd+=( --audio-quality "$quality" )
  fi
  (( embed_metadata ))  && cmd+=( --embed-metadata )
  (( embed_thumbnail )) && cmd+=( --embed-thumbnail )
  cmd+=( "$url" )

  clear_screen
  move 1 3
  printf '%s[1;32mDownloading...%s[0m' "$ESC" "$ESC"
  move 3 3
  printf '%s[1;36msaving songs in: %s%s[0m' "$ESC" "$dir" "$ESC"
  move 4 3
  printf '%s[2m%s%s[0m' "$ESC" "$url" "$ESC"
  move 20 3
  printf '%s[2mCtrl-C aborts%s[0m' "$ESC" "$ESC"

  local line pct saved="" rc=0 seen=0
  while IFS= read -r line; do
    if [[ $line == EXITCODE:* ]]; then
      rc=${line#EXITCODE:}
    elif [[ $line == SAVED:* ]]; then
      saved=${line#SAVED:}
    elif [[ $line == *%* ]]; then
      pct=${line//[% ]/}
      if [[ $pct =~ ^[0-9.]+$ ]]; then
        seen=$(( seen + 1 ))
        draw_bar 6 "$pct" 44
        # dots animation while output flows
        move 1 3
        printf '%s[1;32mDownloading%.*s%s[0m' "$ESC" $(( seen / 8 % 3 + 1 )) "..." "$ESC"
      fi
    fi
  done < <( yt-dlp "${cmd[@]}" 2>&1; printf 'EXITCODE:%d\n' "$?" )

  clear_screen
  local msg color
  if (( rc == 0 )); then
    if [[ -n $saved ]]; then msg="Saved to: $saved"; else msg="Done -> $dir"; fi
    color='1;32'
  else
    msg="download failed (yt-dlp exit $rc)"
    color='1;31'
  fi
  move 10 3
  printf '%s[%sm%s%s[0m' "$ESC" "$color" "${msg:0:74}" "$ESC"
  move 12 3
  printf '%s[2m%s%s[0m' "$ESC" "$url" "$ESC"
  move 14 3
  printf 'press any key to continue'
  IFS= read -rsn1
  REPLY="$msg"
}

# ----------------------------- search flow -----------------------------------
search_flow() {  # $1 query
  local query=$1
  local tmp
  tmp=$(mktemp)

  yt-dlp --flat-playlist \
         --print '%(title)s\t%(channel)s\t%(duration)s\t%(url)s' \
         "ytsearch10:$query" > "$tmp" 2>/dev/null &
  local pid=$! dots=0
  while kill -0 "$pid" 2>/dev/null; do
    clear_screen
    move 10 6
    printf '%s[1;32mSearching%.*s%s[0m' "$ESC" $(( dots % 3 + 1 )) "..." "$ESC"
    move 12 6
    printf '%s[2m%s%s[0m' "$ESC" "$query" "$ESC"
    dots=$(( dots + 1 ))
    sleep 0.25
  done
  wait "$pid" || { rm -f "$tmp"; status="search failed"; return; }

  local -a titles=() chans=() durs=() urls=() items=()
  local t c d u m s i
  while IFS=$'\t' read -r t c d u; do
    [[ -n $u ]] || continue
    if [[ $d =~ ^[0-9]+$ ]]; then
      m=$(( d / 60 )); s=$(( d % 60 ))
      d=$(printf '%d:%02d' "$m" "$s")
    else
      d="?"
    fi
    titles+=( "$t" ); chans+=( "$c" ); durs+=( "$d" ); urls+=( "$u" )
  done < "$tmp"
  rm -f "$tmp"

  if (( ${#urls[@]} == 0 )); then
    status="no results found"
    return
  fi

  for i in "${!urls[@]}"; do
    items+=( "$(printf '%-50s %-14s %5s' \
               "${titles[i]:0:50}" "${chans[i]:0:14}" "${durs[i]}")" )
  done

  # results list: Enter downloads, q goes back to the search page
  local keep=0
  while pick_list "results for '$query'" items "$keep" \
        "up/down select   Enter download   q back to search"; do
    keep=$REPLY
    run_download "${urls[REPLY]}"
    status=$REPLY
  done
}

# ----------------------------- actions ---------------------------------------
do_go() {
  local q
  q=$(printf '%s' "$text" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  if [[ -z $q ]]; then
    status="type a song name or URL first"
    return
  fi
  if ! command -v yt-dlp >/dev/null 2>&1; then
    status="yt-dlp not found - pip install yt-dlp"
    return
  fi
  if ! command -v ffmpeg >/dev/null 2>&1; then
    status="ffmpeg not found - install it to convert audio"
    return
  fi
  if [[ $q =~ ^https?:// ]]; then
    run_download "$q"
    status=$REPLY
  else
    search_flow "$q"
  fi
}

enter_action() {
  case $1 in
    1 ) local -a citems=()
        local i
        for i in "${!CONTAINER_LABELS[@]}"; do
          citems+=( "$(printf '%-10s %s' \
                     "${CONTAINER_LABELS[i]}" "${CONTAINER_DESCS[i]}")" )
        done
        if pick_list "audio container" citems; then
          container=${CONTAINER_FMTS[REPLY]}
        fi ;;
    2 ) if pick_list "audio quality (bitrate)" QUALITIES; then
          quality=${QUALITIES[REPLY]}
        fi ;;
    4 ) embed_metadata=$(( 1 - embed_metadata )) ;;
    5 ) embed_thumbnail=$(( 1 - embed_thumbnail )) ;;
    7 ) do_go ;;
  esac
  save_config
}

# ----------------------------- main loop --------------------------------------
if (( BASH_VERSINFO[0] < 4 )); then
  echo "bash 4 or newer is required"
  exit 1
fi

alt_screen_on
hide_cursor

while :; do
  draw_form
  read_key
  status=""
  if (( sel == 0 )); then
    handle_edit_keys text tcur
  elif (( sel == 3 )); then
    handle_edit_keys download_dir fcur
  else
    case "$key" in
      "$UP" | k )    move_sel -1 ;;
      "$DOWN" | j )  move_sel 1 ;;
      "$ESC" | q )  exit 0 ;;
      "$ENTER" )    enter_action "$sel" ;;
    esac
  fi
done
