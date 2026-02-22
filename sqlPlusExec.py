# domi 2025

import argparse
import subprocess
import json
import re
import time
import win32file
import win32pipe
import pywintypes
import os
import pandas as pd
from io import StringIO
from tabulate import tabulate
from datetime import datetime

gDebug = False
gNoDebug = False

PIPE_NAME = r"\\.\pipe\sqlPlusExec"

MAX_SERVER_START_ATTEMPTS = 5
STOP_SERVER_MSG = "###stop server###"
START_OF_OUT = "##### start of out {} #####"
END_OF_OUT = "##### end of out {} #####"

def log(aText):
    print(str(datetime.now()), aText)
# end of log


def debug(aText):
    if gDebug:
        print(str(datetime.now()), aText)
# end of debug

def waitForPrompt(aProcess, aPrompt="not connected"):
    while True:
        # Read one line at a time from stdout
        lLine = aProcess.stdout.readline()
        if not lLine:
            # Process terminated or no more output
            break
        if aPrompt in lLine.lower():
            return True
    return False
# end of waitForPrompt


# Reads stdout from aProcess.
# Returns only parts between START_OF_OUT and END_OF_OUT.
def getStdOut(aProcess, aCmdCt):
    lOutput = ""
    lStart = False

    while True:
        # Read one line at a time from stdout
        lLine = aProcess.stdout.readline()
        if not lLine:
            # Process terminated or no more output
            break

        if END_OF_OUT.format(aCmdCt) in lLine:
            break

        if lStart:
            lOutput += lLine

        if START_OF_OUT.format(aCmdCt) in lLine:
            lStart = True

    return lOutput
# end of getStdOut


# Send the command to sqlplus
def sqlPlusExec(aProcess, aCmds, aCmdCt):
    debug(f"sqlPlusExec cmd: {aCmds} cmdCt: {aCmdCt}")

    aProcess.stdin.write("clear screen\n\n\n")
    aProcess.stdin.write("prompt " + START_OF_OUT.format(aCmdCt) + " \n")
    for lCmd in aCmds:
        aProcess.stdin.write(lCmd+"\n")
    aProcess.stdin.write("prompt " + END_OF_OUT.format(aCmdCt) + " \n")
    aProcess.stdin.flush()

# end of sqlPlusExec


# Main function for server processing.
# First, it starts sqlplus session.
# Then, it creates a named pipe and waits for client to send commands.
# Once message received, it checks connection string:
#   If the same as before, then it just runs the second command.
#   If different, then reconnects and then runs the second command.
# When processing finished, the server waits for another client interraction.
def server(aSqlplusLogin):
    debug("Server processing..")
    debug(f"aSqlplusLogin: {aSqlplusLogin}")

    # Launch sqlplus process
    debug("Starting sqlplus..")
    lProcess = subprocess.Popen(
        ["sqlplus", "-S", "/nolog"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0
    )
    debug("Sqlplus started.")

    lConnStr = ""
    lCmdCt = 0

    # Wait for process to start to be ready..
    if waitForPrompt(lProcess):
        # Now, start the pipe server
        keepRunning = True
        while keepRunning:
            debug("Starting named pipe server..")
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1, 65536, 65536,
                0,
                None
            )

            debug("")
            debug("============================================================")
            debug("")
            debug("Waiting for client to connect..")
            win32pipe.ConnectNamedPipe(pipe, None)
            debug("Client connected.")

            try:
                while True:
                    result, message = win32file.ReadFile(pipe, 64*1024)
                    data = message.decode("utf-8")
                    debug(f"Received: {data}")

                    params = json.loads(data)
                    debug(f"Received parameters: {params}")

                    if params["conn"].lower() == STOP_SERVER_MSG:
                        debug("Exiting server.")
                        keepRunning = False
                        break

                    if params["conn"].lower() != lConnStr.lower():
                        # Different connection string, reconnect.
                        lConnStr = params["conn"]
                        debug("------------------------------------------------------------")
                        debug("Reconnect [" + re.sub(r"/[^@]+", "", lConnStr) + "]..")
                        sqlPlusExec( lProcess
                                   , [f"conn {lConnStr}"] + aSqlplusLogin
                                   , -1
                                   )
                        debug("------------------------------------------------------------")

                    # Now execute the file or query.
                    lCmdCt += 1

                    lCmds = params["sqlCmd"]

                    if params["isSelect"]:
                        # If query, set sqlplus to return results in csv format.
                        lCmds = ["set markup csv on"] + lCmds + ["set markup csv off"]

                    sqlPlusExec(lProcess, lCmds, lCmdCt)

                    lStdOut = getStdOut(lProcess, lCmdCt)
                    debug(f"lStdOut: {lStdOut}")

                    # Send a confirmation back to client.
                    win32file.WriteFile(pipe, lStdOut.encode("utf-8"))

            except pywintypes.error as e:
                debug(f"Error: {e}")

            finally:
                win32file.CloseHandle(pipe)
                debug("Pipe closed.")

# end of server

def stopServer():
    client(STOP_SERVER_MSG, None, None)
# end of stopServer


def outputResult(aData, aIsSelect, aOutputFormat):
    debug(f"Output={aOutputFormat}")
    debug(f"IsSelect={aIsSelect}")

    lData = aData.strip()

    if aOutputFormat is None or aOutputFormat == "csv" or "no rows selected" in lData or "ERROR at line" in lData or not aIsSelect:
        print(aData)
    else:
        # Remove "x rows selected" message.
        lLines = lData.split('\n')
        lFiltered = [
            line for line in lLines
            if not (line.strip().endswith("rows selected.") and not line.lower().startswith("no rows selected"))
        ]
        lData = '\n'.join(lFiltered)

        lDf = pd.read_csv(StringIO(lData), dtype=str)

        if aOutputFormat == "align":
            print(lDf)
        else:
            # Reset the index to include it as a column
            lDfReset = lDf.reset_index().rename(columns={'index': 'rn'})
            # Add 1 to the index column to start at 1 instead of 0
            lDfReset['rn'] = lDfReset['rn'] + 1
            # Replace NaN with None
            lDfReset = lDfReset.where(pd.notnull(lDfReset), None)
            # Convert DataFrame to a list of lists for tabulate
            lTable = lDfReset.values.tolist()
            # Get the column names including the index column
            lColumnNames = lDfReset.columns.tolist()

            print(tabulate(lTable, headers=lColumnNames, tablefmt=aOutputFormat))

# end of outputResult


# Main function for client processing.
# Attempt to connect to a named pipe server.
# If not successful, start the server, attempt MAX_SERVER_START_ATTEMPTS times to connect again.
# When successfully connected, send the request.
def client(aConn, aSqlCmd, aOutputFormat=None):
    debug("Client processing..")
    debug(f"Conn={aConn}")
    debug(f"SqlCmd={aSqlCmd}")
    debug(f"OutputFormat={aOutputFormat}")

    debug("Connecting to named pipe server..")

    lStartCt = 0
    while True:
        try:
            handle = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )
            break
        except Exception as e:
            if lStartCt == 0:
                debug("Server not found, starting a new instance..")
                # subprocess.Popen(['python', __file__, "-start"], creationflags=subprocess.CREATE_NEW_CONSOLE)
                # subprocess.Popen(['python', 'other_app.py'], creationflags=subprocess.CREATE_NEW_CONSOLE)
                # subprocess.Popen(['python', 'other_app.py'], creationflags=subprocess.CREATE_NO_WINDOW)
                # creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW
                lStartCmd = f"start python {__file__} -start"
                if not gNoDebug:
                    lStartCmd += " -debug" 
                subprocess.Popen(lStartCmd, shell=True)

            else:
                debug(f"Waiting for server..{e}")
                time.sleep(1)

            lStartCt += 1
            debug(f"lStartCt: {lStartCt}")

            if lStartCt > MAX_SERVER_START_ATTEMPTS:
                debug("Unable to start server")
                break

    if lStartCt < MAX_SERVER_START_ATTEMPTS:
        debug("Connected to named pipe server.")

        lIsSelect = False
        if  (   not aSqlCmd is None
            and len(aSqlCmd) > 0 
            and (re.match(r'^select(\W|$)', aSqlCmd[0].lstrip().lower()) 
                    or re.match(r'^with(\W|$)', aSqlCmd[0].lstrip().lower())
                )
        ):
            lIsSelect = True

        params = {
              "conn": aConn
            , "sqlCmd": aSqlCmd
            , "isSelect": lIsSelect
        }
        message = json.dumps(params)

        # Write message to pipe
        win32file.WriteFile(handle, message.encode("utf-8"))

        result, data = win32file.ReadFile(handle, 64*1024)

        lOutputFormat = aOutputFormat
        if lOutputFormat is None:
            lOutputFormat = "csv"

        outputResult(data.decode('utf-8'), lIsSelect, lOutputFormat)

# end of client


def main():
    lParser = argparse.ArgumentParser(description="sqlplus executor, client/server mode.")

    lStartStopGrp = lParser.add_mutually_exclusive_group(required=False)
    lStartStopGrp.add_argument("-start",   action="store_true", default=False, help="Start server.")
    lStartStopGrp.add_argument("-stop",    action="store_true", default=False, help="Stop server.")

    lDebugGrp = lParser.add_mutually_exclusive_group(required=False)
    lDebugGrp.add_argument("-debug",   action="store_true", help="Client runs in nodebug mode by default. Use to switch debug on.")
    lDebugGrp.add_argument("-nodebug", action="store_true", help="Server runs in debug mode by default. Use to switch debug off.")
  
    lParser.add_argument("-conn", type=str, help="Connection string [username/password@tnsname].", required=False)

    lParser.add_argument("-sqlcmd", type=str, nargs="+", help="Multiple values, each representing one line to run in sqlplus session.", required=False)
    lParser.add_argument("-outputformat", type=str, choices=["csv", "align", "simple", "psql", "presto", "fancy_grid"], help="Format of query output.", required=False)

    lArgs = lParser.parse_args()

    # Default and mandatory startup commands.
    lConfigDefault = {
                        "sqlplus_login": [
                              "set linesize 512"
                            , "col error for a220"
                            , "set timing off"
                            , "set serveroutput on"
                        ]
                     }
    try:
        # Get the directory where the current script is located.
        lScriptDir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(lScriptDir, 'sqlPlusExec.config')) as f:
            lConfig = json.load(f)
            lConfig["sqlplus_login"] = lConfigDefault["sqlplus_login"] + lConfig["sqlplus_login"]
    except Exception as e:
        None

    global gDebug
    global gNoDebug 

    if not lArgs.start and not lArgs.stop:
        if lArgs.conn is None:
            lParser.error("-conn is required for client.")
        if lArgs.sqlcmd is None:
            lParser.error("-sqlcmd is required for client.")

        gNoDebug = True
        if lArgs.debug:
            gDebug = True
            gNoDebug = False

        client(lArgs.conn, lArgs.sqlcmd, lArgs.outputformat)

    if lArgs.start:
        gDebug = True
        if lArgs.nodebug:
            gDebug = False
            gNoDebug = True

        server(lConfig.get("sqlplus_login"))

    if lArgs.stop:
        stopServer()

# end of main


if __name__ == "__main__":
    main()

