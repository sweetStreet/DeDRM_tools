#! /usr/bin/python
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab
# For use with Topaz Scripts Version 2.6

class Unbuffered:
    def __init__(self, stream):
        self.stream = stream
    def write(self, data):
        self.stream.write(data)
        self.stream.flush()
    def __getattr__(self, attr):
        return getattr(self.stream, attr)

import sys
sys.stdout=Unbuffered(sys.stdout)

import csv
import os
import getopt
from struct import pack
from struct import unpack

class TpzDRMError(Exception):
    pass

# Get a 7 bit encoded number from string. The most
# significant byte comes first and has the high bit (8th) set

def readEncodedNumber(file):
    flag = False
    c = file.read(1)
    if (len(c) == 0):
        return None
    data = ord(c)

    if data == 0xFF:
        flag = True
        c = file.read(1)
        if (len(c) == 0):
            return None
        data = ord(c)

    if data >= 0x80:
        datax = (data & 0x7F)
        while data >= 0x80 :
            c = file.read(1)
            if (len(c) == 0):
                return None
            data = ord(c)
            datax = (datax <<7) + (data & 0x7F)
        data = datax

    if flag:
        data = -data
    return data


# returns a binary string that encodes a number into 7 bits
# most significant byte first which has the high bit set

def encodeNumber(number):
    result = ""
    negative = False
    flag = 0

    if number < 0 :
        number = -number + 1
        negative = True

    while True:
        byte = number & 0x7F
        number = number >> 7
        byte += flag
        result += chr(byte)
        flag = 0x80
        if number == 0 :
            if (byte == 0xFF and negative == False) :
                result += chr(0x80)
            break

    if negative:
        result += chr(0xFF)

    return result[::-1]



# create / read  a length prefixed string from the file

def lengthPrefixString(data):
    return encodeNumber(len(data))+data

def readString(file):
    stringLength = readEncodedNumber(file)
    if (stringLength == None):
        return ""
    sv = file.read(stringLength)
    if (len(sv)  != stringLength):
        return ""
    return unpack(str(stringLength)+"s",sv)[0]


# convert a binary string generated by encodeNumber (7 bit encoded number)
# to the value you would find inside the page*.dat files to be processed

def convert(i):
    result = ''
    val = encodeNumber(i)
    for j in xrange(len(val)):
        c = ord(val[j:j+1])
        result += '%02x' % c
    return result



# the complete string table used to store all book text content
# as well as the xml tokens and values that make sense out of it

class Dictionary(object):
    def __init__(self, dictFile):
        self.filename = dictFile
        self.size = 0
        self.fo = file(dictFile,'rb')
        self.stable = []
        self.size = readEncodedNumber(self.fo)
        for i in xrange(self.size):
            self.stable.append(self.escapestr(readString(self.fo)))
        self.pos = 0

    def escapestr(self, str):
        str = str.replace('&','&amp;')
        str = str.replace('<','&lt;')
        str = str.replace('>','&gt;')
        str = str.replace('=','&#61;')
        return str

    def lookup(self,val):
        if ((val >= 0) and (val < self.size)) :
            self.pos = val
            return self.stable[self.pos]
        else:
            print "Error - %d outside of string table limits" % val
            raise TpzDRMError('outside of string table limits')
            # sys.exit(-1)

    def getSize(self):
        return self.size

    def getPos(self):
        return self.pos

    def dumpDict(self):
        for i in xrange(self.size):
            print "%d %s %s" % (i, convert(i), self.stable[i])
        return

# parses the xml snippets that are represented by each page*.dat file.
# also parses the other0.dat file - the main stylesheet
# and information used to inject the xml snippets into page*.dat files

class PageParser(object):
    def __init__(self, filename, dict, debug, flat_xml):
        self.fo = file(filename,'rb')
        self.id = os.path.basename(filename).replace('.dat','')
        self.dict = dict
        self.debug = debug
        self.flat_xml = flat_xml
        self.tagpath = []
        self.doc = []
        self.snippetList = []


    # hash table used to enable the decoding process
    # This has all been developed by trial and error so it may still have omissions or
    # contain errors
    # Format:
    # tag : (number of arguments, argument type, subtags present, special case of subtags presents when escaped)

    token_tags = {
        'x'            : (1, 'scalar_number', 0, 0),
        'y'            : (1, 'scalar_number', 0, 0),
        'h'            : (1, 'scalar_number', 0, 0),
        'w'            : (1, 'scalar_number', 0, 0),
        'firstWord'    : (1, 'scalar_number', 0, 0),
        'lastWord'     : (1, 'scalar_number', 0, 0),
        'rootID'       : (1, 'scalar_number', 0, 0),
        'stemID'       : (1, 'scalar_number', 0, 0),
        'type'         : (1, 'scalar_text', 0, 0),

        'info'            : (0, 'number', 1, 0),

        'info.word'            : (0, 'number', 1, 1),
        'info.word.ocrText'    : (1, 'text', 0, 0),
        'info.word.firstGlyph' : (1, 'raw', 0, 0),
        'info.word.lastGlyph'  : (1, 'raw', 0, 0),
        'info.word.bl'         : (1, 'raw', 0, 0),
        'info.word.link_id'    : (1, 'number', 0, 0),

        'glyph'           : (0, 'number', 1, 1),
        'glyph.x'         : (1, 'number', 0, 0),
        'glyph.y'         : (1, 'number', 0, 0),
        'glyph.glyphID'   : (1, 'number', 0, 0),

        'dehyphen'          : (0, 'number', 1, 1),
        'dehyphen.rootID'   : (1, 'number', 0, 0),
        'dehyphen.stemID'   : (1, 'number', 0, 0),
        'dehyphen.stemPage' : (1, 'number', 0, 0),
        'dehyphen.sh'       : (1, 'number', 0, 0),

        'links'        : (0, 'number', 1, 1),
        'links.page'   : (1, 'number', 0, 0),
        'links.rel'    : (1, 'number', 0, 0),
        'links.row'    : (1, 'number', 0, 0),
        'links.title'  : (1, 'text', 0, 0),
        'links.href'   : (1, 'text', 0, 0),
        'links.type'   : (1, 'text', 0, 0),
        'links.id'     : (1, 'number', 0, 0),

        'paraCont'          : (0, 'number', 1, 1),
        'paraCont.rootID'   : (1, 'number', 0, 0),
        'paraCont.stemID'   : (1, 'number', 0, 0),
        'paraCont.stemPage' : (1, 'number', 0, 0),

        'paraStems'        : (0, 'number', 1, 1),
        'paraStems.stemID' : (1, 'number', 0, 0),

        'wordStems'          : (0, 'number', 1, 1),
        'wordStems.stemID'   : (1, 'number', 0, 0),

        'empty'          : (1, 'snippets', 1, 0),

        'page'           : (1, 'snippets', 1, 0),
        'page.class'     : (1, 'scalar_text', 0, 0),
        'page.pageid'    : (1, 'scalar_text', 0, 0),
        'page.pagelabel' : (1, 'scalar_text', 0, 0),
        'page.type'      : (1, 'scalar_text', 0, 0),
        'page.h'         : (1, 'scalar_number', 0, 0),
        'page.w'         : (1, 'scalar_number', 0, 0),
        'page.startID' : (1, 'scalar_number', 0, 0),

        'group'           : (1, 'snippets', 1, 0),
        'group.class'     : (1, 'scalar_text', 0, 0),
        'group.type'      : (1, 'scalar_text', 0, 0),
        'group._tag'      : (1, 'scalar_text', 0, 0),
        'group.orientation': (1, 'scalar_text', 0, 0),

        'region'           : (1, 'snippets', 1, 0),
        'region.class'     : (1, 'scalar_text', 0, 0),
        'region.type'      : (1, 'scalar_text', 0, 0),
        'region.x'         : (1, 'scalar_number', 0, 0),
        'region.y'         : (1, 'scalar_number', 0, 0),
        'region.h'         : (1, 'scalar_number', 0, 0),
        'region.w'         : (1, 'scalar_number', 0, 0),
        'region.orientation' : (1, 'scalar_text', 0, 0),

        'empty_text_region' : (1, 'snippets', 1, 0),

        'img'           : (1, 'snippets', 1, 0),
        'img.x'         : (1, 'scalar_number', 0, 0),
        'img.y'         : (1, 'scalar_number', 0, 0),
        'img.h'         : (1, 'scalar_number', 0, 0),
        'img.w'         : (1, 'scalar_number', 0, 0),
        'img.src'       : (1, 'scalar_number', 0, 0),
        'img.color_src' : (1, 'scalar_number', 0, 0),

        'paragraph'           : (1, 'snippets', 1, 0),
        'paragraph.class'     : (1, 'scalar_text', 0, 0),
        'paragraph.firstWord' : (1, 'scalar_number', 0, 0),
        'paragraph.lastWord'  : (1, 'scalar_number', 0, 0),
        'paragraph.lastWord'  : (1, 'scalar_number', 0, 0),
        'paragraph.gridSize'  : (1, 'scalar_number', 0, 0),
        'paragraph.gridBottomCenter'  : (1, 'scalar_number', 0, 0),
        'paragraph.gridTopCenter' : (1, 'scalar_number', 0, 0),
        'paragraph.gridBeginCenter' : (1, 'scalar_number', 0, 0),
        'paragraph.gridEndCenter' : (1, 'scalar_number', 0, 0),


        'word_semantic'           : (1, 'snippets', 1, 1),
        'word_semantic.type'      : (1, 'scalar_text', 0, 0),
        'word_semantic.class'     : (1, 'scalar_text', 0, 0),
        'word_semantic.firstWord' : (1, 'scalar_number', 0, 0),
        'word_semantic.lastWord'  : (1, 'scalar_number', 0, 0),

        'word'            : (1, 'snippets', 1, 0),
        'word.type'       : (1, 'scalar_text', 0, 0),
        'word.class'      : (1, 'scalar_text', 0, 0),
        'word.firstGlyph' : (1, 'scalar_number', 0, 0),
        'word.lastGlyph'  : (1, 'scalar_number', 0, 0),

        '_span'           : (1, 'snippets', 1, 0),
        '_span.class'     : (1, 'scalar_text', 0, 0),
        '_span.firstWord' : (1, 'scalar_number', 0, 0),
        '_span.lastWord'  : (1, 'scalar_number', 0, 0),
        '_span.gridSize'  : (1, 'scalar_number', 0, 0),
        '_span.gridBottomCenter'  : (1, 'scalar_number', 0, 0),
        '_span.gridTopCenter' : (1, 'scalar_number', 0, 0),
        '_span.gridBeginCenter' : (1, 'scalar_number', 0, 0),
        '_span.gridEndCenter' : (1, 'scalar_number', 0, 0),

        'span'           : (1, 'snippets', 1, 0),
        'span.firstWord' : (1, 'scalar_number', 0, 0),
        'span.lastWord'  : (1, 'scalar_number', 0, 0),
        'span.gridSize'  : (1, 'scalar_number', 0, 0),
        'span.gridBottomCenter'  : (1, 'scalar_number', 0, 0),
        'span.gridTopCenter' : (1, 'scalar_number', 0, 0),
        'span.gridBeginCenter' : (1, 'scalar_number', 0, 0),
        'span.gridEndCenter' : (1, 'scalar_number', 0, 0),

        'extratokens'            : (1, 'snippets', 1, 0),
        'extratokens.type'       : (1, 'scalar_text', 0, 0),
        'extratokens.firstGlyph' : (1, 'scalar_number', 0, 0),
        'extratokens.lastGlyph'  : (1, 'scalar_number', 0, 0),

        'glyph.h'      : (1, 'number', 0, 0),
        'glyph.w'      : (1, 'number', 0, 0),
        'glyph.use'    : (1, 'number', 0, 0),
        'glyph.vtx'    : (1, 'number', 0, 1),
        'glyph.len'    : (1, 'number', 0, 1),
        'glyph.dpi'    : (1, 'number', 0, 0),
        'vtx'          : (0, 'number', 1, 1),
        'vtx.x'        : (1, 'number', 0, 0),
        'vtx.y'        : (1, 'number', 0, 0),
        'len'          : (0, 'number', 1, 1),
        'len.n'        : (1, 'number', 0, 0),

        'book'         : (1, 'snippets', 1, 0),
        'version'      : (1, 'snippets', 1, 0),
        'version.FlowEdit_1_id'            : (1, 'scalar_text', 0, 0),
        'version.FlowEdit_1_version'       : (1, 'scalar_text', 0, 0),
        'version.Schema_id'                : (1, 'scalar_text', 0, 0),
        'version.Schema_version'           : (1, 'scalar_text', 0, 0),
        'version.Topaz_version'            : (1, 'scalar_text', 0, 0),
        'version.WordDetailEdit_1_id'      : (1, 'scalar_text', 0, 0),
        'version.WordDetailEdit_1_version' : (1, 'scalar_text', 0, 0),
        'version.ZoneEdit_1_id'            : (1, 'scalar_text', 0, 0),
        'version.ZoneEdit_1_version'       : (1, 'scalar_text', 0, 0),
        'version.chapterheaders'           : (1, 'scalar_text', 0, 0),
        'version.creation_date'            : (1, 'scalar_text', 0, 0),
        'version.header_footer'            : (1, 'scalar_text', 0, 0),
        'version.init_from_ocr'            : (1, 'scalar_text', 0, 0),
        'version.letter_insertion'         : (1, 'scalar_text', 0, 0),
        'version.xmlinj_convert'           : (1, 'scalar_text', 0, 0),
        'version.xmlinj_reflow'            : (1, 'scalar_text', 0, 0),
        'version.xmlinj_transform'         : (1, 'scalar_text', 0, 0),
        'version.findlists'                : (1, 'scalar_text', 0, 0),
        'version.page_num'                 : (1, 'scalar_text', 0, 0),
        'version.page_type'                : (1, 'scalar_text', 0, 0),
        'version.bad_text'                 : (1, 'scalar_text', 0, 0),
        'version.glyph_mismatch'           : (1, 'scalar_text', 0, 0),
        'version.margins'                  : (1, 'scalar_text', 0, 0),
        'version.staggered_lines'          : (1, 'scalar_text', 0, 0),
        'version.paragraph_continuation'   : (1, 'scalar_text', 0, 0),
        'version.toc'                      : (1, 'scalar_text', 0, 0),

        'stylesheet'                : (1, 'snippets', 1, 0),
        'style'                     : (1, 'snippets', 1, 0),
        'style._tag'                : (1, 'scalar_text', 0, 0),
        'style.type'                : (1, 'scalar_text', 0, 0),
        'style._after_type'         : (1, 'scalar_text', 0, 0),
        'style._parent_type'        : (1, 'scalar_text', 0, 0),
        'style._after_parent_type'  : (1, 'scalar_text', 0, 0),
        'style.class'               : (1, 'scalar_text', 0, 0),
        'style._after_class'        : (1, 'scalar_text', 0, 0),
        'rule'                      : (1, 'snippets', 1, 0),
        'rule.attr'                 : (1, 'scalar_text', 0, 0),
        'rule.value'                : (1, 'scalar_text', 0, 0),

        'original'      : (0, 'number', 1, 1),
        'original.pnum' : (1, 'number', 0, 0),
        'original.pid'  : (1, 'text', 0, 0),
        'pages'        : (0, 'number', 1, 1),
        'pages.ref'    : (1, 'number', 0, 0),
        'pages.id'     : (1, 'number', 0, 0),
        'startID'      : (0, 'number', 1, 1),
        'startID.page' : (1, 'number', 0, 0),
        'startID.id'   : (1, 'number', 0, 0),

     }


    # full tag path record keeping routines
    def tag_push(self, token):
        self.tagpath.append(token)
    def tag_pop(self):
        if len(self.tagpath) > 0 :
            self.tagpath.pop()
    def tagpath_len(self):
        return len(self.tagpath)
    def get_tagpath(self, i):
        cnt = len(self.tagpath)
        if i < cnt : result = self.tagpath[i]
        for j in xrange(i+1, cnt) :
            result += '.' + self.tagpath[j]
        return result


    # list of absolute command byte values values that indicate
    # various types of loop meachanisms typically used to generate vectors

    cmd_list = (0x76, 0x76)

    # peek at and return 1 byte that is ahead by i bytes
    def peek(self, aheadi):
        c = self.fo.read(aheadi)
        if (len(c) == 0):
            return None
        self.fo.seek(-aheadi,1)
        c = c[-1:]
        return ord(c)


    # get the next value from the file being processed
    def getNext(self):
        nbyte = self.peek(1);
        if (nbyte == None):
            return None
        val = readEncodedNumber(self.fo)
        return val


    # format an arg by argtype
    def formatArg(self, arg, argtype):
        if (argtype == 'text') or (argtype == 'scalar_text') :
            result = self.dict.lookup(arg)
        elif (argtype == 'raw') or (argtype == 'number') or (argtype == 'scalar_number') :
            result = arg
        elif (argtype == 'snippets') :
            result = arg
        else :
            print "Error Unknown argtype %s" % argtype
            sys.exit(-2)
        return result


    # process the next tag token, recursively handling subtags,
    # arguments, and commands
    def procToken(self, token):

        known_token = False
        self.tag_push(token)

        if self.debug : print 'Processing: ', self.get_tagpath(0)
        cnt = self.tagpath_len()
        for j in xrange(cnt):
            tkn = self.get_tagpath(j)
            if tkn in self.token_tags :
                num_args = self.token_tags[tkn][0]
                argtype = self.token_tags[tkn][1]
                subtags = self.token_tags[tkn][2]
                splcase = self.token_tags[tkn][3]
                ntags = -1
                known_token = True
                break

        if known_token :

            # handle subtags if present
            subtagres = []
            if (splcase == 1):
                # this type of tag uses of escape marker 0x74 indicate subtag count
                if self.peek(1) == 0x74:
                    skip = readEncodedNumber(self.fo)
                    subtags = 1
                    num_args = 0

            if (subtags == 1):
                ntags = readEncodedNumber(self.fo)
                if self.debug : print 'subtags: ' + token + ' has ' + str(ntags)
                for j in xrange(ntags):
                    val = readEncodedNumber(self.fo)
                    subtagres.append(self.procToken(self.dict.lookup(val)))

            # arguments can be scalars or vectors of text or numbers
            argres = []
            if num_args > 0 :
                firstarg = self.peek(1)
                if (firstarg in self.cmd_list) and (argtype != 'scalar_number') and (argtype != 'scalar_text'):
                    # single argument is a variable length vector of data
                    arg = readEncodedNumber(self.fo)
                    argres = self.decodeCMD(arg,argtype)
                else :
                    # num_arg scalar arguments
                    for i in xrange(num_args):
                        argres.append(self.formatArg(readEncodedNumber(self.fo), argtype))

            # build the return tag
            result = []
            tkn = self.get_tagpath(0)
            result.append(tkn)
            result.append(subtagres)
            result.append(argtype)
            result.append(argres)
            self.tag_pop()
            return result

        # all tokens that need to be processed should be in the hash
        # table if it may indicate a problem, either new token
        # or an out of sync condition
        else:
            result = []
            if (self.debug):
                print 'Unknown Token:', token
            self.tag_pop()
            return result


    # special loop used to process code snippets
    # it is NEVER used to format arguments.
    # builds the snippetList
    def doLoop72(self, argtype):
        cnt = readEncodedNumber(self.fo)
        if self.debug :
            result = 'Set of '+ str(cnt) + ' xml snippets. The overall structure \n'
            result += 'of the document is indicated by snippet number sets at the\n'
            result += 'end of each snippet. \n'
            print result
        for i in xrange(cnt):
            if self.debug: print 'Snippet:',str(i)
            snippet = []
            snippet.append(i)
            val = readEncodedNumber(self.fo)
            snippet.append(self.procToken(self.dict.lookup(val)))
            self.snippetList.append(snippet)
        return



    # general loop code gracisouly submitted by "skindle" - thank you!
    def doLoop76Mode(self, argtype, cnt, mode):
        result = []
        adj = 0
        if mode & 1:
            adj = readEncodedNumber(self.fo)
        mode = mode >> 1
        x = []
        for i in xrange(cnt):
            x.append(readEncodedNumber(self.fo) - adj)
        for i in xrange(mode):
            for j in xrange(1, cnt):
                x[j] = x[j] + x[j - 1]
        for i in xrange(cnt):
            result.append(self.formatArg(x[i],argtype))
        return result


    # dispatches loop commands bytes with various modes
    # The 0x76 style loops are used to build vectors

    # This was all derived by trial and error and
    # new loop types may exist that are not handled here
    # since they did not appear in the test cases

    def decodeCMD(self, cmd, argtype):
        if (cmd == 0x76):

            # loop with cnt, and mode to control loop styles
            cnt = readEncodedNumber(self.fo)
            mode = readEncodedNumber(self.fo)

            if self.debug : print 'Loop for', cnt, 'with  mode', mode,  ':  '
            return self.doLoop76Mode(argtype, cnt, mode)

        if self.dbug: print  "Unknown command", cmd
        result = []
        return result



    # add full tag path to injected snippets
    def updateName(self, tag, prefix):
        name = tag[0]
        subtagList = tag[1]
        argtype = tag[2]
        argList = tag[3]
        nname = prefix + '.' + name
        nsubtaglist = []
        for j in subtagList:
            nsubtaglist.append(self.updateName(j,prefix))
        ntag = []
        ntag.append(nname)
        ntag.append(nsubtaglist)
        ntag.append(argtype)
        ntag.append(argList)
        return ntag



    # perform depth first injection of specified snippets into this one
    def injectSnippets(self, snippet):
        snipno, tag = snippet
        name = tag[0]
        subtagList = tag[1]
        argtype = tag[2]
        argList = tag[3]
        nsubtagList = []
        if len(argList) > 0 :
            for j in argList:
                asnip = self.snippetList[j]
                aso, atag = self.injectSnippets(asnip)
                atag = self.updateName(atag, name)
                nsubtagList.append(atag)
        argtype='number'
        argList=[]
        if len(nsubtagList) > 0 :
            subtagList.extend(nsubtagList)
        tag = []
        tag.append(name)
        tag.append(subtagList)
        tag.append(argtype)
        tag.append(argList)
        snippet = []
        snippet.append(snipno)
        snippet.append(tag)
        return snippet



    # format the tag for output
    def formatTag(self, node):
        name = node[0]
        subtagList = node[1]
        argtype = node[2]
        argList = node[3]
        fullpathname = name.split('.')
        nodename = fullpathname.pop()
        ilvl = len(fullpathname)
        indent = ' ' * (3 * ilvl)
        rlst = []
        rlst.append(indent + '<' + nodename + '>')
        if len(argList) > 0:
            alst = []
            for j in argList:
                if (argtype == 'text') or (argtype == 'scalar_text') :
                    alst.append(j + '|')
                else :
                    alst.append(str(j) + ',')
            argres = "".join(alst)
            argres = argres[0:-1]
            if argtype == 'snippets' :
                rlst.append('snippets:' + argres)
            else :
                rlst.append(argres)
        if len(subtagList) > 0 :
            rlst.append('\n')
            for j in subtagList:
                if len(j) > 0 :
                    rlst.append(self.formatTag(j))
            rlst.append(indent + '</' + nodename + '>\n')
        else:
            rlst.append('</' + nodename + '>\n')
        return "".join(rlst)


    # flatten tag
    def flattenTag(self, node):
        name = node[0]
        subtagList = node[1]
        argtype = node[2]
        argList = node[3]
        rlst = []
        rlst.append(name)
        if (len(argList) > 0):
            alst = []
            for j in argList:
                if (argtype == 'text') or (argtype == 'scalar_text') :
                    alst.append(j + '|')
                else :
                    alst.append(str(j) + '|')
            argres = "".join(alst)
            argres = argres[0:-1]
            if argtype == 'snippets' :
                rlst.append('.snippets=' + argres)
            else :
                rlst.append('=' + argres)
        rlst.append('\n')
        for j in subtagList:
            if len(j) > 0 :
                rlst.append(self.flattenTag(j))
        return "".join(rlst)


    # reduce create xml output
    def formatDoc(self, flat_xml):
        rlst = []
        for j in self.doc :
            if len(j) > 0:
                if flat_xml:
                    rlst.append(self.flattenTag(j))
                else:
                    rlst.append(self.formatTag(j))
        result = "".join(rlst)
        if self.debug : print result
        return result



    # main loop - parse the page.dat files
    # to create structured document and snippets

    # FIXME: value at end of magic appears to be a subtags count
    # but for what?  For now, inject an 'info" tag as it is in
    # every dictionary and seems close to what is meant
    # The alternative is to special case the last _ "0x5f" to mean something

    def process(self):

        # peek at the first bytes to see what type of file it is
        magic = self.fo.read(9)
        if (magic[0:1] == 'p') and (magic[2:9] == 'marker_'):
            first_token = 'info'
        elif (magic[0:1] == 'p') and (magic[2:9] == '__PAGE_'):
            skip = self.fo.read(2)
            first_token = 'info'
        elif (magic[0:1] == 'p') and (magic[2:8] == '_PAGE_'):
            first_token = 'info'
        elif (magic[0:1] == 'g') and (magic[2:9] == '__GLYPH'):
            skip = self.fo.read(3)
            first_token = 'info'
        else :
            # other0.dat file
            first_token = None
            self.fo.seek(-9,1)


        # main loop to read and build the document tree
        while True:

            if first_token != None :
                # use "inserted" first token 'info' for page and glyph files
                tag = self.procToken(first_token)
                if len(tag) > 0 :
                    self.doc.append(tag)
                first_token = None

            v = self.getNext()
            if (v == None):
                break

            if (v == 0x72):
                self.doLoop72('number')
            elif (v > 0) and (v < self.dict.getSize()) :
                tag = self.procToken(self.dict.lookup(v))
                if len(tag) > 0 :
                    self.doc.append(tag)
            else:
                if self.debug:
                    print "Main Loop:  Unknown value: %x" % v
                if (v == 0):
                    if (self.peek(1) == 0x5f):
                        skip = self.fo.read(1)
                        first_token = 'info'

        # now do snippet injection
        if len(self.snippetList) > 0 :
            if self.debug : print 'Injecting Snippets:'
            snippet = self.injectSnippets(self.snippetList[0])
            snipno = snippet[0]
            tag_add = snippet[1]
            if self.debug : print self.formatTag(tag_add)
            if len(tag_add) > 0:
                self.doc.append(tag_add)

        # handle generation of xml output
        xmlpage = self.formatDoc(self.flat_xml)

        return xmlpage


def fromData(dict, fname):
    flat_xml = True
    debug = False
    pp = PageParser(fname, dict, debug, flat_xml)
    xmlpage = pp.process()
    return xmlpage

def getXML(dict, fname):
    flat_xml = False
    debug = False
    pp = PageParser(fname, dict, debug, flat_xml)
    xmlpage = pp.process()
    return xmlpage

def usage():
    print 'Usage: '
    print '    convert2xml.py dict0000.dat infile.dat '
    print ' '
    print ' Options:'
    print '   -h            print this usage help message '
    print '   -d            turn on debug output to check for potential errors '
    print '   --flat-xml    output the flattened xml page description only '
    print ' '
    print '     This program will attempt to convert a page*.dat file or '
    print ' glyphs*.dat file, using the dict0000.dat file, to its xml description. '
    print ' '
    print ' Use "cmbtc_dump.py" first to unencrypt, uncompress, and dump '
    print ' the *.dat files from a Topaz format e-book.'

#
# Main
#

def main(argv):
    dictFile = ""
    pageFile = ""
    debug = False
    flat_xml = False
    printOutput = False
    if len(argv) == 0:
        printOutput = True
        argv = sys.argv

    try:
        opts, args = getopt.getopt(argv[1:], "hd", ["flat-xml"])

    except getopt.GetoptError, err:

        # print help information and exit:
        print str(err) # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    if len(opts) == 0 and len(args) == 0 :
        usage()
        sys.exit(2)

    for o, a in opts:
        if o =="-d":
            debug=True
        if o =="-h":
            usage()
            sys.exit(0)
        if o =="--flat-xml":
            flat_xml = True

    dictFile, pageFile = args[0], args[1]

    # read in the string table dictionary
    dict = Dictionary(dictFile)
    # dict.dumpDict()

    # create a page parser
    pp = PageParser(pageFile, dict, debug, flat_xml)

    xmlpage = pp.process()

    if printOutput:
        print xmlpage
        return 0

    return xmlpage

if __name__ == '__main__':
    sys.exit(main(''))
