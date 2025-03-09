LUA_BIN=$1
SCRIPT_TO_RUN=$2
$LUA_BIN $SCRIPT_TO_RUN 2>/dev/null &
pid=$!

# Wait for process is started and running.
sleep 3
if ! kill -0 "$pid" 2>/dev/null; then
    echo 'ERR'
    exit 1
fi

# Send SIGINT and wait for termination.
kill -INT "$pid" 2>/dev/null
sleep 3

# Terminated? OK, signal handled -- 'sigaction() behavior'.
if ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid" 2>/dev/null
    echo 'OK'
    exit 0
fi

# Not terminated -- 'signal() BSD-behavior'.
kill -KILL "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
echo 'FAIL'
exit 0
