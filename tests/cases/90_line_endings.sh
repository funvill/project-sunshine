# Carriage returns in files that are copied to the Pi, the NAS or Home Assistant.
# A CR breaks a shell script on Linux ("\r: command not found") and ends a value in an env file.
# The check reads the INDEX version, so it guards the repository, not one Windows checkout.
# A CR in a working copy only warns: .gitattributes makes git write LF, so it means a checkout from
# before that rule, and the file works once it is checked out again.
section "line endings: no CR in what gets deployed"
REPO="$(dirname "$HERE")"
DEPLOY_DIRS="pi homeassistant nas experiments tests/stubs"
if ! git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  echo "  SKIP: not a git checkout, so there is no index to check"
else
  # i/ column of `git ls-files --eol`: lf, crlf, mixed, none, -text (binary)
  cr_in_index() { git -C "$REPO" ls-files --eol -- $DEPLOY_DIRS | awk '$1=="i/crlf" || $1=="i/mixed" {print}' | grep . ; }
  bad_files="$(cr_in_index || true)"
  if [[ -z "$bad_files" ]]; then ok; else bad "CR in the index version of:"; echo "$bad_files" | sed 's/^/    /'; fi
  check "there are deployable files to look at" test -n "$(git -C "$REPO" ls-files -- $DEPLOY_DIRS | head -n1)"
  warn_files="$(git -C "$REPO" ls-files --eol -- $DEPLOY_DIRS | awk '$2=="w/crlf" || $2=="w/mixed" {print}')"
  if [[ -n "$warn_files" ]]; then
    echo "  WARN: carriage returns in these working copies (the index is fine; check the file out again):"
    echo "$warn_files" | sed 's/^/    /'
  fi
fi
