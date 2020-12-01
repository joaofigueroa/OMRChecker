"""

Designed and Developed by-
Udayraj Deshmukh
https://github.com/Udayraj123

"""

from time import localtime, strftime, time
from csv import QUOTE_NONNUMERIC
from glob import glob
import re
import os
import cv2
import json
import argparse
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import imutils
import app.config as config
import app.utils as utils

from app.template import Template

from fastapi import Depends, FastAPI, HTTPException, Body, File, UploadFile, Form

app = FastAPI()

# Local globals
filesMoved = 0
filesNotMoved = 0


@app.get("/")
def read_root():
    return {"JG-OMR Service"}


@app.post("/uploadfile/")
async def find_alternatives_marked(template: str = Form(...), file: UploadFile = File(...)):

    template_json = template

    argparser = argparse.ArgumentParser()

    argparser.add_argument("-o", "--outputDir", default='outputs', required=False,
                           dest='output_dir', help="Specify an output directory.")

    args, unknown = argparser.parse_known_args()
    args = vars(args)

    paths = config.Paths(os.path.join(args['output_dir']))

    args_local = []

    final_template = Template(template_json)

    return {json.dumps(process_files([file], final_template, args_local))}


# # TODO(beginner task) :-
# # from colorama import init
# # init()
# # from colorama import Fore, Back, Style


def checkAndMove(error_code, filepath, filepath2):
    # print("Dummy Move:  "+filepath, " --> ",filepath2)
    global filesNotMoved
    filesNotMoved += 1
    return True

    global filesMoved
    if(not os.path.exists(filepath)):
        print('File already moved')
        return False
    if(os.path.exists(filepath2)):
        print('ERROR : Duplicate file at ' + filepath2)
        return False

    print("Moved:  " + filepath, " --> ", filepath2)
    os.rename(filepath, filepath2)
    filesMoved += 1
    return True


def processOMR(template, omrResp):
    # Note: This is a reference function. It is not part of the OMR checker
    # So its implementation is completely subjective to user's requirements.
    csvResp = {}

    # symbol for absent response
    UNMARKED_SYMBOL = ''

    # print("omrResp",omrResp)

    # Multi-column/multi-row questions which need to be concatenated
    for qNo, respKeys in template.concats.items():
        csvResp[qNo] = ''.join([omrResp.get(k, UNMARKED_SYMBOL)
                                for k in respKeys])

    # Single-column/single-row questions
    for qNo in template.singles:
        csvResp[qNo] = omrResp.get(qNo, UNMARKED_SYMBOL)

    # Note: Concatenations and Singles together should be mutually exclusive
    # and should cover all questions in the template(exhaustive)
    # TODO: ^add a warning if omrResp has unused keys remaining
    return csvResp


def report(
        Status,
        streak,
        scheme,
        qNo,
        marked,
        ans,
        prevmarks,
        currmarks,
        marks):
    print(
        '%s \t %s \t\t %s \t %s \t %s \t %s \t %s ' % (qNo,
                                                       Status,
                                                       str(streak),
                                                       '[' + scheme + '] ',
                                                       (str(
                                                           prevmarks) + ' + ' + str(currmarks) + ' =' + str(marks)),
                                                       str(marked),
                                                       str(ans)))

# check sectionwise only.


def evaluate(resp, squad="H", explain=False):
    # TODO: @contributors - Need help generalizing this function
    global Answers, Sections
    marks = 0
    answers = Answers[squad]
    if(explain):
        print('Question\tStatus \t Streak\tSection \tMarks_Update\tMarked:\tAnswer:')
    for scheme, section in Sections[squad].items():
        sectionques = section['ques']
        prevcorrect = None
        allflag = 1
        streak = 0
        for q in sectionques:
            qNo = 'q' + str(q)
            ans = answers[qNo]
            marked = resp.get(qNo, 'X')
            firstQ = sectionques[0]
            lastQ = sectionques[len(sectionques) - 1]
            unmarked = marked == 'X' or marked == ''
            bonus = 'BONUS' in ans
            correct = bonus or (marked in ans)
            inrange = 0

            if(unmarked or int(q) == firstQ):
                streak = 0
            elif(prevcorrect == correct):
                streak += 1
            else:
                streak = 0

            if('allNone' in scheme):
                # loop on all sectionques
                allflag = allflag and correct
                if(q == lastQ):
                    # at the end check allflag
                    prevcorrect = correct
                    currmarks = section['marks'] if allflag else 0
                else:
                    currmarks = 0

            elif('Proxy' in scheme):
                a = int(ans[0])
                # proximity check
                inrange = 1 if unmarked else (
                    float(abs(int(marked) - a)) / float(a) <= 0.25)
                currmarks = section['+marks'] if correct else (
                    0 if inrange else -section['-marks'])

            elif('Fibo' in scheme or 'Power' in scheme or 'Boom' in scheme):
                currmarks = section['+seq'][streak] if correct else (
                    0 if unmarked else -section['-seq'][streak])
            elif('TechnoFin' in scheme):
                currmarks = 0
            else:
                print('Invalid Sections')
            prevmarks = marks
            marks += currmarks

            if(explain):
                if bonus:
                    report('BonusQ', streak, scheme, qNo, marked,
                           ans, prevmarks, currmarks, marks)
                elif correct:
                    report('Correct', streak, scheme, qNo, marked,
                           ans, prevmarks, currmarks, marks)
                elif unmarked:
                    report('Unmarked', streak, scheme, qNo, marked,
                           ans, prevmarks, currmarks, marks)
                elif inrange:
                    report('InProximity', streak, scheme, qNo,
                           marked, ans, prevmarks, currmarks, marks)
                else:
                    report('Incorrect', streak, scheme, qNo,
                           marked, ans, prevmarks, currmarks, marks)

            prevcorrect = correct

    return marks


def setup_output(paths, template):
    ns = argparse.Namespace()
    print("\nChecking Files...")

    # Include current output paths
    ns.paths = paths

    # custom sort: To use integer order in question names instead of
    # alphabetical - avoids q1, q10, q2 and orders them q1, q2, ..., q10
    ns.respCols = sorted(list(template.concats.keys()) + template.singles,
                         key=lambda x: int(x[1:]) if ord(x[1]) in range(48, 58) else 0)
    ns.emptyResp = [''] * len(ns.respCols)
    ns.sheetCols = ['file_id', 'input_path',
                    'output_path', 'score'] + ns.respCols
    ns.OUTPUT_SET = []
    ns.filesObj = {}
    ns.filesMap = {
        "Results": paths.resultDir + 'Results_' + timeNowHrs + '.csv',
        "MultiMarked": paths.manualDir + 'MultiMarkedFiles_.csv',
        "Errors": paths.manualDir + 'ErrorFiles_.csv',
        "BadRollNos": paths.manualDir + 'BadRollNoFiles_.csv'
    }

    for fileKey, fileName in ns.filesMap.items():
        if(not os.path.exists(fileName)):
            print("Note: Created new file: %s" % (fileName))
            # still append mode req [THINK!]
            ns.filesObj[fileKey] = open(fileName, 'a')
            # Create Header Columns
            pd.DataFrame([ns.sheetCols], dtype=str).to_csv(
                ns.filesObj[fileKey], quoting=QUOTE_NONNUMERIC, header=False, index=False)
        else:
            print('Present : appending to %s' % (fileName))
            ns.filesObj[fileKey] = open(fileName, 'a')

    return ns


def process_files(omr_files, template, args):
    start_time = int(time())
    filesCounter = 0
    filesNotMoved = 0

    for filepath in omr_files:

        inOMR = cv2.imdecode(np.fromstring(
            bytes(filepath.file.read()), np.uint8), cv2.IMREAD_GRAYSCALE)

        print(
            '\n[%d] Processing image: \t' %
            (filesCounter),
            filepath,
            "\tResolution: ",
            inOMR.shape)

        OMRCrop = utils.getROI(inOMR, filepath.filename)

        if(OMRCrop is None):

            print("Inside OMRCrop If ")
            # Error OMR - could not crop
            # newfilepath = out.paths.errorsDir + filename
            # out.OUTPUT_SET.append([filename] + out.emptyResp)
            # if(checkAndMove(config.NO_MARKER_ERR, filepath, newfilepath)):
            #     err_line = [filename, filepath,
            #                 newfilepath, "NA"] + out.emptyResp
            #     pd.DataFrame(
            #         err_line,
            #         dtype=str).T.to_csv(
            #         out.filesObj["Errors"],
            #         quoting=QUOTE_NONNUMERIC,
            #         header=False,
            #         index=False)
            continue

        if template.marker is not None:
            OMRCrop = utils.handle_markers(OMRCrop, template.marker, filename)

        file_id = "id_teste"

        OMRresponseDict, final_marked, MultiMarked, multiroll = \
            utils.readResponse(template, OMRCrop, name=file_id)

        # concatenate roll nos, set unmarked responses, etc
        resp = processOMR(template, OMRresponseDict)

        if resp is None:
            return "Parece que a foto não ficou muito boa. Tente usar um fundo mais escuro"
        else:
            return resp

        for x in [utils.thresholdCircles]:
            if(x != []):
                x = pd.DataFrame(x)
                print(x.describe())
                plt.plot(range(len(x)), x)
                plt.title("Mystery Plot")
                plt.show()
            else:
                print(x)
