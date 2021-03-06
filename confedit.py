#!/usr/bin/env python3
#
# decrypt and modify the router configuration file to recover VOIP and
# other passwords in plain text and to unlock hidden or disabled
# functions.
#
# License informations are available in the LICENSE file
#
import tempfile
import string
import random
import re
import sys
import base64
import os
import io
import queue
import logging
import signal
import tkinter as tk
import configparser
import gettext
import locale

from pathlib import Path
from tkinter import *
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk , VERTICAL, HORIZONTAL, N, S, E, W
from tkinter.filedialog import askopenfilename, asksaveasfilename
from Cryptodome.Cipher import AES # requires pycrypto
from lxml import etree as ET
from io import StringIO

#------------------------------------------------------------------------------
# Some variable meanings:
#   data_in     encrypted configuration binary file in this binary string
#   data_out    decrypted configuration file: xml binary string
#   cpedata_bin encrypted cpe configuration in binary string
#   cpedata_hex encrypted cpe configuration in base64 encoded binary string
#   cpedata_out decrypted cpe configuration file: xml binary string
#------------------------------------------------------------------------------

#------------------------------------------------------------------------------
# global variables pointing to default file names
#------------------------------------------------------------------------------
mydir    = sys.path[0]              # not correct on exe file from pyinstaller
mydir    = os.path.dirname(os.path.realpath(__file__))
down_pem = mydir + '/download.pem'
up_pem   = mydir + '/upload.pem'

randomstr  = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(4))
tmpradix   = tempfile.gettempdir() + '/' + randomstr + '-'
tmpconf    = tmpradix + 'conf.xml'
tmpconfcpe = tmpradix + 'confcpe.xml'
fversion   = mydir + '/version'

homedir    = str(Path.home())
defaultdir = homedir
loaded_bin = 0                   # binary config loaded
loaded_xml = 0                   # xml config loaded
loaded_cpe = 0                   # cpe xml config loaded
versionstr = ''

load_pems_done = 0               # pem files loaded
inidir      = os.environ.get('APPDATA',homedir)   # default location for .confedit.ini
inifile     = inidir + '/.confedit.ini'
userinifile = inifile                             # ini file in user folder
proginifile = mydir + '/.confedit.ini'            # ini file in program folder
blank20     = '                   '

def language_set(lan):
    global _
    if (os.path.isdir(mydir + '/locale/' + lan)):
        slan = gettext.translation('adbtools2', localedir='locale', languages=[lan])
        slan.install()
    else:
        _ = lambda s: s

def language_default():
    global iniconfig
    lan = 'EN'
    try:
        lan = iniconfig['global']['Language']
    except:
        (lancode, lanenc) = locale.getdefaultlocale()
        lancode2=lancode[0:2]
        if (os.path.isdir(mydir + '/locale/' + lancode)):
            lan = lancode
        if (os.path.isdir(mydir + '/locale/' + lancode2)):
            lan = lancode2
        else:
            lan = 'en'
    return lan
        
def show_restricted():
    global cpedata_out
    sout = get_restricted(cpedata_out)
    logger.log(linfo,sout)

def save_restricted():
    global cpedata_out
    global defaultdir
    sout = get_restricted(cpedata_out)
    name = asksaveasfilename(initialdir=defaultdir,
                             filetypes =((_("Text file"), "*.txt"),(_("All Files"),"*.*")),
                             title = _("Restricted Text File")
                             )
    print (name)
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'w') as f:
            f.write(sout)
    except:
        print(_("Error writing: "),name)
        sys.exit(1)

    defaultdir=os.path.dirname(name)
#------------------------------------------------------------------------------
# read_inifile    read the initial configuration file and careate one if it
#                 does not exist
#------------------------------------------------------------------------------
def read_inifile():
    global iniconfig
    global inifile
    global defaultdir
    iniconfig = configparser.ConfigParser()
    if os.path.isfile(inifile):
        iniconfig.read(inifile)
        defaultdir=iniconfig['global']['SaveLoadDir']
    else:
        iniconfig['global'] = {'LogDebug':                  'yes',
                               'SaveLoadDirLastLocation':   'yes',
                               'SaveLoadDir':               defaultdir,
                               'PreferenceInProgramFolder': 'no',
                               'Language':                   language_default()}
        write_inifile()

#------------------------------------------------------------------------------
# write_inifile   write the configuration file, iniconfig dictionary must
#                 already exist
#------------------------------------------------------------------------------
def write_inifile():
    global iniconfig
    global inifile
    with open(inifile,'w') as configfile:
        iniconfig.write(configfile)
        
#------------------------------------------------------------------------------
# get_restricted return a string with restricted commands in the cpe xml
#     input: xml_str it is cpedata_out
#------------------------------------------------------------------------------
def get_restricted(xml_str):
    global rtr_ip
    global sweb     # restricted web commands
    global scli     # restricted cli commands
    mystr   = re.sub(b'<!-- DATA.*', b'', xml_str, 0, re.DOTALL)
    xmltree = ET.parse(io.BytesIO(mystr))
    xmlroot = xmltree.getroot()

    sweb = '';
    scli = '';

    for i in xmlroot.findall(".//X_ADB_AccessControl/Feature/PagePath"):
        web = i.text
        parent = i.getparent()
        perm = ''
        for child in parent:
            if child.tag == 'Permissions':
                perm = child.text
        print(i.text)
        print(perm)

        if perm == '0000':
            print(web[0:4])
            if web[0:4] == 'dboa':
                sweb = sweb + "\n" + "    " + "http://" + rtr_ip.get() + "/ui/" + web
            else:
                scli = scli + "\n" + "    " + web
    sout="\nRestricted web urls\n" + sweb + "\n" + "\nRestricted CLI commands\n" + scli
    return(sout)


#------------------------------------------------------------------------------
#    <PagePath>dboard/storage/ftpserver</PagePath>
#    <Origin>CPE</Origin>
#    <Permissions>2221</Permissions>
#    <PagePath>clish/configure/management/webGui</PagePath>
#    <Origin>CPE</Origin>
#    <Permissions>0000</Permissions>

def enable_restricted_web():
    global cpedata_out
    cpedata_out = re.sub(b'(<PagePath>dboa\S+</PagePath>.\s+<Origin>\S+.\s+<Permissions>)0000',b'\g<1>2221',cpedata_out, 0, re.DOTALL)
    logger.log(lerr,_("Unlocked restricted web pages"))
    get_info(cpedata_out)    # update router status info
    
def enable_restricted_cli():
    global cpedata_out
    cpedata_out = re.sub(b'(<PagePath>clis\S+</PagePath>.\s+<Origin>\S+.\s+<Permissions>)0000',b'\g<1>2221',cpedata_out, 0, re.DOTALL)
    cpedata_out = re.sub(b'(<PagePath>clis\S+ EnableButtonbackToFactory</PagePath>.\s+<Origin>\S+.\s+<Permissions>)0000',b'\g<1>2221',cpedata_out, 0, re.DOTALL)
    logger.log(lerr,_("Unlocked restricted commands in CLI"))
    get_info(cpedata_out)   # update router status info

#<Name>dlinkddns.com</Name>
#<Name>dlinkdns.com</Name>

def fix_dlinkddns():
    global cpedata_out
    cpedata_out = re.sub(b'<Name>dlinkdns.com</Name>',b'<Name>dlinkddns.com</Name>',cpedata_out, 0, re.DOTALL)
    logger.log(lerr,_("Fixed dlinkdns -> dlinkddns"))
    get_info(cpedata_out)   # update router status info    
    
#------------------------------------------------------------------------------
# get_info     setup router info textvariables
#     input    xml_str   binary string, xml or cpe xml conf file
#------------------------------------------------------------------------------
def get_info (xml_str):
    global  rtr_hwversion
    global  sweb
    global  scli
    mystr   = re.sub(b'<!-- DATA.*', b'', xml_str, 0, re.DOTALL)
    xmltree = ET.parse(io.BytesIO(mystr))
    xmlroot = xmltree.getroot()

    sout = '';

    for i in xmlroot.findall(".//DeviceInfo/HardwareVersion"):
        rtr_hwversion.set(i.text)

    for i in xmlroot.findall(".//DeviceInfo/Manufacturer"):
        rtr_manufacturer.set(i.text)

    for i in xmlroot.findall(".//DeviceInfo/ModelName"):
        rtr_modelname.set(i.text)

    for i in xmlroot.findall(".//DeviceInfo/SerialNumber"):
        rtr_serial.set(i.text)

    for i in xmlroot.findall(".//DeviceInfo/X_DLINK_fw_upgr_permitted"):
        rtr_fwupgrade.set(i.text)
    print("rtr_fwupgrade.get():" + rtr_fwupgrade.get()  + ":")
    if rtr_fwupgrade.get() == blank20 :
        rtr_fwupgrade.set('undef')
        
    for i in xmlroot.findall(".//DeviceInfo/X_DLINK_customer_ID"):
        rtr_customerid.set(i.text)

    for i in xmlroot.findall(".//DeviceInfo/X_DLINK_BsdGuiVisible"):
        rtr_bsdgui.set(i.text)

    for i in xmlroot.findall(".//DeviceInfo/X_DLINK_AllowFirmwareDowngrade"):
        rtr_fwdowngrade.set(i.text)
    print("rtr_fwupgrade.get():" + rtr_fwupgrade.get()  + ":")
    if rtr_fwdowngrade.get() == blank20 :
        rtr_fwdowngrade.set('undef')
        
    for i in xmlroot.findall(".//IP/Interface/IPv4Address/IPAddress"):
        parent = i.getparent()
        granpa = parent.getparent()
        for child in granpa:
            if (child.tag == 'Alias') and (child.text == 'Bridge'):
                rtr_ip.set(i.text)

    for i in xmlroot.findall(".//IP/Interface/IPv4Address/SubnetMask"):
        parent = i.getparent()
        granpa = parent.getparent()
        for child in granpa:
            if (child.tag == 'Alias') and (child.text == 'Bridge'):
                rtr_mask.set(i.text)

    sout = get_restricted(cpedata_out)
    if (sweb == ''):
        rtr_rwebgui.set(_('Unlocked'))
    else:
        rtr_rwebgui.set(_('Locked'))

    if (scli == ''):
        rtr_rcli.set(_('Unlocked'))
    else:
        rtr_rcli.set(_('Locked'))

    if (re.search(b'<Name>dlinkddns.com</Name>',cpedata_out,0)):
        rtr_fixddns.set(_('Fixed'))
    else:
        rtr_fixddns.set(_('Not Fixed'))
        
#------------------------------------------------------------------------------
# get_passwords return a string text file with passwords xml string
#     input    xml_str   binary string, xml or cpe xml conf file
#     rturn    text string 
#------------------------------------------------------------------------------
def get_passwords (xml_str):
    mystr   = re.sub(b'<!-- DATA.*', b'', xml_str, 0, re.DOTALL)
    xmltree = ET.parse(io.BytesIO(mystr))
    xmlroot = xmltree.getroot()

    sout = '';
    
    for s in  [ 'AuthPassword', 'Password' ]:
        for i in xmlroot.findall(".//" + s):
            parent  = i.getparent()
            granpa  = parent.getparent()
            try: granpa2s = granpa.getparent().tag
            except: granpa2s=''
            if ((granpa2s != 'X_ADB_MobileModem') and i.text is not None):
                sout = sout + granpa2s + '/' + granpa.tag + '/' + parent.tag + "\n"
                for child in parent:
                    if (child.tag in ['Name', 'AuthUserName', 'Password', 'AuthPassword', 'Username',
                                      'Enable', 'Url', 'Alias', 'Hostname' ]):
                        sout = sout + "  " + "%-15s" % (child.tag) + "  " + child.text + "\n"

                sout = sout + "\n"
    return(sout)

#------------------------------------------------------------------------------
# check_enable_menu - check and, if needed, enable menut items 
#------------------------------------------------------------------------------
def check_enable_menu ():
    global loaded_bin
    global loaded_xml
    global loaded_cpe
    global filem
    global infom
    global editm
    global menubar
    global rtr_hwversion
    global rtr_manufacturer
    global rtr_modelname
    global rtr_serial
    global rtr_fwupgrade
    global rtr_customerid
    global rtr_bsdgui
    global rtr_fwdowngrade
    global rtr_ip
    global rtr_mask
    global rtr_rwebgui
    global rtr_rcli
    global rtr_fixddns

    print("check_enable_menu - loaded_bin, loaded_xml, loaded_cpe",loaded_bin,loaded_xml,loaded_cpe)
    
    if ((loaded_bin == 1 ) or ((loaded_xml == 1) and (loaded_cpe == 1))):
        filem.entryconfig(4, state = NORMAL)     # save as bin config
        filem.entryconfig(5, state = NORMAL)     # save as xml config
        filem.entryconfig(6, state = NORMAL)     # save as cpe xml config
        editm.entryconfig(1, state = NORMAL)     # enable/unlock restricted webgui
        editm.entryconfig(2, state = NORMAL)     # enable/unlock restricted CLI commands
        editm.entryconfig(3, state = NORMAL)     # enable firmware downgrade        
        editm.entryconfig(4, state = NORMAL)     # enable fix dlinkdns -> dlinkddns        
    else:
        filem.entryconfig(4, state = DISABLED)   # save as bin config 
        filem.entryconfig(5, state = DISABLED)   # save as xml config
        filem.entryconfig(6, state = DISABLED)   # save as cpe xml config

    if ((loaded_bin == 1) or (loaded_xml == 1) or (loaded_cpe == 1)):
        infom.entryconfig(1, state = NORMAL)     # show passwords
        infom.entryconfig(3, state = NORMAL)     # save passwords
    else:
        infom.entryconfig(1, state = DISABLED)   # show passwords
        infom.entryconfig(3, state = DISABLED)   # save passwords

    if ((loaded_bin == 1) or (loaded_cpe == 1)):
        infom.entryconfig(2, state = NORMAL)     # show restricted commands
        infom.entryconfig(4, state = NORMAL)     # save restricted commands
    else:
        infom.entryconfig(2, state = DISABLED)   # show restricted commands
        infom.entryconfig(4, state = DISABLED)   # save restricted commands
        
        
    if ((loaded_bin == 0) and (loaded_cpe == 0)):
        rtr_hwversion.set(blank20)
        rtr_manufacturer.set(blank20)
        rtr_modelname.set(blank20)
        rtr_serial.set(blank20)
        rtr_fwupgrade.set(blank20)
        rtr_customerid.set(blank20)
        rtr_bsdgui.set(blank20)
        rtr_fwdowngrade.set(blank20)
        rtr_ip.set(blank20)
        rtr_mask.set(blank20)
        rtr_rwebgui.set(blank20)
        rtr_rcli.set(blank20)
        rtr_fixddns.set(blank20)
        
    logger.log(level,_("check_enable_menu - done"))

#------------------------------------------------------------------------------
# load_pems - load pem files
#------------------------------------------------------------------------------
def load_pems():
    global pemconf_data, pemcpe_data
    try:
        with open(down_pem, "rb") as f:
            pemconf_data = f.read()
    except:
        logger.log(lerr,_("load_pems - error opening "), down_pem)
        popupmsg(_('Severe Error'), _("A severe error occoured in 'load_pems'.\nFile missing: ") + down_pem +"\n")
        conferror_quit(1)

    try:
        with open(up_pem, "rb") as f:
            pemcpe_data = f.read()
    except:
        logger.log(lerr,_("load_pems - error opening "), up_pem)
        popupmsg(_('Severe Error'), _("A severe error occoured in 'load_pems'.\nFile missing: ") + up_pem + "\n")
        conferror_quit(1)
        
    load_pems_done = 1
    logger.log(ldebug,_("load_pems - done"))
    logger.log(ldebug,_("len 1: ") + str(len(pemconf_data)))
    logger.log(ldebug,_("len 2: ") + str(len(pemcpe_data)))
    

#------------------------------------------------------------------------------
# about - 
#------------------------------------------------------------------------------
def about():
    global versionstr
    global fversion
    aboutstr=''
    aboutstr=aboutstr.join([_("ADB Configuration Editor (confedit)\nCopyright (c) 2018 Valerio Di Giampietro (main program)\nCopyright (c) 2017 Gabriel Huber (decrypting algorithm)\nCopyright (c) 2017 Benjamin Bertrand (windows interface)\n\nLicense informations available in the LICENSE file\n\nTHE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n\n")])

    if (versionstr == ''):
        with open(fversion,"r") as f:
            versionstr = f.read()
            logger.log(ldebug,_("about - reading ") + fversion)
    popupmsg(_('About'), aboutstr + _("Program version: ") + versionstr + "\n")

#------------------------------------------------------------------------------
# enable_fw_upgrade   enable fw upgrade/downgrade 
#------------------------------------------------------------------------------
def enable_fw_upgrade():
    global cpedata_out
    global rtr_fwupgrade
    global rtr_fwdowngrade
    cpedata_out = re.sub(b'<X_DLINK_fw_upgr_permitted>false</X_DLINK_fw_upgr_permitted>',
                         b'<X_DLINK_fw_upgr_permitted>true</X_DLINK_fw_upgr_permitted>',
                         cpedata_out,
                         0,
                         re.DOTALL)

    cpedata_out = re.sub(b'<X_DLINK_AllowFirmwareDowngrade>false</X_DLINK_AllowFirmwareDowngrade>',
                         b'<X_DLINK_AllowFirmwareDowngrade>true</X_DLINK_AllowFirmwareDowngrade>',
                         cpedata_out,
                         0,
                         re.DOTALL)

    if (rtr_fwupgrade.get() == 'undef'):
        print ("rtr_fwupgrade is undef")
        cpedata_out = re.sub(b'(</X_ADB_TR098Ready>.)(\s+<X_DLINK_customer_ID>\S+.)',
                             b'\g<1><X_DLINK_fw_upgr_permitted>true</X_DLINK_fw_upgr_permitted>\g<2>',
                             cpedata_out,
                             0,
                             re.DOTALL)


    if (rtr_fwdowngrade.get() == 'undef'):
        print ("rtr_fwdowngrade is undef")
        cpedata_out = re.sub(b'(</X_DLINK_BsdGuiVisible>.)(\s+<X_ADB_PowerManagement\S+.)',
                             b'\g<1><X_DLINK_AllowFirmwareDowngrade>true</X_DLINK_AllowFirmwareDowngrade>\g<2>',
                             cpedata_out,
                             0,
                             re.DOTALL)
        
        
    get_info(cpedata_out)
    logger.log(lerr,_("enable_fw_upgrade - firmware upgrade/downgrade enabled"))
    
#------------------------------------------------------------------------------
# load_config - load binary router configuration file - ok
#------------------------------------------------------------------------------
def load_config(*args):
    global data_out
    global cpedata_out
    global defaultdir
    global loaded_bin
    global loaded_xml
    global loaded_cpe
    global pemcpe_data
    global pem_data
    global xml_src
    global cpexml_src

    name = askopenfilename(initialdir=defaultdir,
                           filetypes =((_("Configuration File"), "*.bin"),(_("All Files"),"*.*")),
                           title = _("Binary Configuration File")
                           )


    try:
        logger.log(ldebug,_("load_config - loading ") + name)

    except:
        logger.log(ldebug,_("load_config - no file selected"))
        return()

    if (name == ''):
        logger.log(ldebug,-("load_config - no file selected"))
        return()
    
    
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'rb') as f:
            data_in = f.read()
    except:
        logger.log(lerr,_("load_config - error opening "),name)
        logger.log(lerr,_("load_config - error opening "),name)
        load_bin = 0
        load_xml = 0
        load_cpe = 0
        check_enable_menu()
        xml_src.set('')
        cpexml_src.set('')
        return()


    defaultdir=os.path.dirname(name)
    logger.log(ldebug,_("defaultdir: ") + defaultdir)
    if (not load_pems_done):
        load_pems()

    logger.log(ldebug,_("len data_in: ") + str(len(data_in)))
    # decrypt config

    # Going for the popular choice...
    IV = b"\x00" * AES.block_size

    # Just take a random chunk out of the file and use it as our key
    key = pemconf_data[0x20:0x30]
    cipher = AES.new(key, AES.MODE_CBC, IV)

    try:
        data_out = cipher.decrypt(data_in)

    except:
        logger.log(ldebug,_("load_config - error in decrypting data\nWrong input file?"))
        popupmsg(_('Error in input file'),_("Error in decrypting data\nWrong input file?"))
        return()

    # Padding is a badly implemented PKCS#7 where 16 bytes padding is ignored,
    # so we have to check all previous bytes to see if it is valid.
    padding_length = data_out[-1]
    if (padding_length < AES.block_size) & (padding_length < len(data_out)):
        for i in range(0, padding_length):
            if data_out[-1 - i] != padding_length:
                break
            else:
                data_out = data_out[:-padding_length]

    #-------------------------------------------------------------------------
    # extract the cpe xml data
    #-------------------------------------------------------------------------

    #<!-- CPE Data: DVA-5592/DVA-5592 system type    : 963138_VD5920 -->
    #<!-- DATA
    #9V/jO+TpbscUypF/41d3Ej15nwHuUp+c4wBWV4uFWb1Zb/nS6QuDiLUoZeJ2s0mksjXrARR2

    match = re.search(b'<!-- DATA.(.*).-->', data_out, re.DOTALL)

    if match:
        cpedata_hex = match.group(1)
    else:
        logger.log(lerr,_("load_config - error in finding hex data") + "\n")
        popupmsg(_('Severe Error'), _("A severe error occurred in 'load_config'.\nUnable to extract CPE XML configuration."))
        conferror_quit(2)
    
    cpedata_bin = base64.b64decode(cpedata_hex)
    
    key = pemcpe_data[0x20:0x30]
    cipher = AES.new(key, AES.MODE_CBC, IV)    
    cpedata_out = cipher.decrypt(cpedata_bin)
    # Padding is a badly implemented PKCS#7 where 16 bytes padding is ignored,
    # so we have to check all previous bytes to see if it is valid.
    padding_length = cpedata_out[-1]
    if (padding_length < AES.block_size) & (padding_length < len(cpedata_out)):
        for i in range(0, padding_length):
            if cpedata_out[-1 - i] != padding_length:
                break
            else:
                cpedata_out = cpedata_out[:-padding_length]
    logger.log(ldebug,_("load_config - length cpedata_out ") + str(len(cpedata_out)))
    loaded_bin = 1
    loaded_xml = 0
    loaded_cpe = 0
    check_enable_menu()
    #print_passwords()
    get_info(cpedata_out)
    xml_src.set(name)
    cpexml_src.set(name)
    
#------------------------------------------------------------------------------
# load_xmlconfig - load xml router configuration file - ok
#------------------------------------------------------------------------------
def load_xmlconfig(*args):
    global defaultdir
    global loaded_bin
    global loaded_xml
    global loaded_cpe
    global data_out
    global defaultdir
    name = askopenfilename(initialdir=defaultdir,
                           filetypes =((_("XML Configuration File"), "*.xml"),(_("All Files"),"*.*")),
                           title = _("XML Configuration File")
                           )
    print (name)
    try:
        logger.log(ldebug,_("load_xmlconfig - loading ") + name)

    except:
        logger.log(ldebug,_("load_xmlconfig - no file selected"))
        return()

    if (name == ''):
        logger.log(ldebug,_("load_xmlconfig - no file selected"))
        return()
    
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'rb') as f:
            data_out = f.read()
    except:
        logger.log(lerr,_("load_xmlconfig - error opening "), name)
        load_bin = 0
        load_xml = 0
        load_cpe = 0
        check_enable_menu()
        xml_src.set('')
        cpexml_src.set('')
        return()

    defaultdir=os.path.dirname(name)
    loaded_xml = 1
    loaded_bin = 0
    check_enable_menu()
    if (not load_pems_done):
        load_pems()
    xml_src.set(name)
    if (loaded_cpe == 0):
        cpexml_src.set('')
    check_enable_menu()
    
#------------------------------------------------------------------------------
# load_cpexmlconfig - load cpe xml router configuration file - ok 
#------------------------------------------------------------------------------
def load_cpexmlconfig(*args):
    global defaultdir
    global cpedata_out
    global loaded_cpe
    global loaded_xml
    global loaded_bin
    name = askopenfilename(initialdir=defaultdir,
                           filetypes =(("CPE XML Configuration file", "*.xml"),("All Files","*.*")),
                           title = _("CPE XML Configuration File")
                           )
    print (name)

    try:
        logger.log(ldebug,_("load_cpexmlconfig - loading ") + name)

    except:
        logger.log(ldebug,_("load_cpexmlconfig - no file selected"))
        return()

    if (name == ''):
        logger.log(ldebug,-("load_cpexmlconfig - no file selected"))
        return()
    
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'rb') as f:
            cpedata_out = f.read()
    except:
        logger.log(lerr,_("load_cpexmlconfig - error opening "),name)
        load_bin = 0
        load_xml = 0
        load_cpe = 0
        check_enable_menu()
        xml_src.set('')
        cpexml_src.set('')
        return()

    defaultdir=os.path.dirname(name)
    loaded_cpe = 1
    loaded_bin = 0
    if (loaded_xml == 0):
        xml_src.set('')
    check_enable_menu()
    if (not load_pems_done):
        load_pems()
    cpexml_src.set(name)
    get_info(cpedata_out)
    check_enable_menu()
                                    
#------------------------------------------------------------------------------
# save_config - save router binary configuration file - ok
#------------------------------------------------------------------------------
def save_config(*args):
    global defaultdir
    global data_out
    global cpedata_out
    global pemcpe_data
    global pemconf_data

    if (not load_pems_done):
        load_pems()

    # -------------------------------------------------------------------------
    # encode and base 64 cpe data
    # -------------------------------------------------------------------------
    # Going for the popular choice...
    IV = b"\x00" * AES.block_size

    key = pemcpe_data[0x20:0x30]
    cipher = AES.new(key, AES.MODE_CBC, IV)

    padding_length = AES.block_size - (len(cpedata_out) % AES.block_size)
    if padding_length != AES.block_size:
        padding_byte = padding_length.to_bytes(1, "big")
        cpedata_out += padding_byte * padding_length
        
    cpedata_in  = cipher.encrypt(cpedata_out)
    cpedata_hex = base64.b64encode(cpedata_in)
    cpedata2_hex = re.sub(b"(.{72})", b"\\1\n", cpedata_hex, 0, re.DOTALL)

    # -------------------------------------------------------------------------
    # insert data cpe in hex format inside the main xml data and encrypt all
    # -------------------------------------------------------------------------

    # #<!-- CPE Data: DVA-5592/DVA-5592 system type    : 963138_VD5920 -->
    # #<!-- DATA
    # #9V/jO+TpbscUypF/41d3Ej15nwHuUp+c4wBWV4uFWb1Zb/nS6QuDiLUoZeJ2s0mksjXrARR2


    data_out = re.sub(b'<!-- DATA\n(.*)\n-->',
                      b"<!-- DATA\n" + cpedata2_hex + b"\n-->",
                      data_out, 1, re.DOTALL)

    key = pemconf_data[0x20:0x30]
    cipher = AES.new(key, AES.MODE_CBC, IV)

    padding_length = AES.block_size - (len(data_out) % AES.block_size)
    if padding_length != AES.block_size:
        padding_byte = padding_length.to_bytes(1, "big")
        data_out += padding_byte * padding_length
        
    data_in = cipher.encrypt(data_out)

    # -------------------------------------------------------------------------
    # write binary file
    # -------------------------------------------------------------------------
    
    name = asksaveasfilename(initialdir=defaultdir,
                             filetypes =((_("Binary Configuration File"), "*.bin"),(_("All Files"),"*.*")),
                             title =_("Binary Configuration File")
                             )
    print (name)
    try:
        logger.log(ldebug,_("save_config - saving ") + name)

    except:
        logger.log(ldebug,_("save_config - no file selected"))
        return()

    if (name == ''):
        logger.log(ldebug,_("save_config - no file selected"))
        return()

    
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'wb') as f:
            f.write(data_in)
    except:
        logger.log(lerr,_("save_config - error opening "),name)
        check_enable_menu()
        return()

    defaultdir=os.path.dirname(name)

#------------------------------------------------------------------------------
# save_xmlconfig - save router xml configuration file - ok
#------------------------------------------------------------------------------
def save_xmlconfig(*args):
    global defaultdir
    name = asksaveasfilename(initialdir=defaultdir,
                             filetypes =((_("XML configuration file"), "*.xml"),(_("All Files"),"*.*")),
                             title = _("Save XML Configuration File")
                             )
    try:
        logger.log(ldebug,_("save_xmlconfig - saving ") + name)

    except:
        logger.log(ldebug,_("save_xmlconfig - no file selected"))
        return()

    if (name == ''):
        logger.log(ldebug,_("save_xmlconfig - no file selected"))
        return()
    
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'wb') as f:
            f.write(data_out)
    except:
        logger.log(lerr,_("save_config - error opening "),name)
        check_enable_menu()
        return()

    defaultdir=os.path.dirname(name)

#------------------------------------------------------------------------------
# save_cpexmlconfig - save router configuration file - ok
#------------------------------------------------------------------------------
def save_cpexmlconfig(*args):
    global defaultdir
    global cpedata_out
    name = asksaveasfilename(initialdir=defaultdir,
                             filetypes =((_("XML Configuration File"), "*.xml"),(_("All Files"),"*.*")),
                             title = _("Save CPE XML Configuration File")
                             )

    
    try:
        logger.log(ldebug,_("save_cpexmlconfig - saving ") + name)

    except:
        logger.log(ldebug,_("save_cpexmlconfig - no file selected"))
        return()

    if (name == ''):
        logger.log(ldebug,-("save_cpexmlconfig - no file selected"))
        return()
    
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'wb') as f:
            f.write(cpedata_out)
    except:
        logger.log(lerr,_("save_cpexmlconfig - error opening "),name)
        check_enable_menu()
        return()

    defaultdir=os.path.dirname(name)

                                
#------------------------------------------------------------------------------
# confquit - quit the program
#------------------------------------------------------------------------------
def confquit(*args):
    print("Conf quit")
    sys.exit(0)

def conferror_quit(err):
    logger.log(lerr,_("Exit with error ") + err)
    sys.exit(err)
    
#------------------------------------------------------------------------------
# not_yet - print in the console the not implemented yet message
#------------------------------------------------------------------------------
def not_yet(mstr=''):
    logger.log(lerr, mstr + _("not implemented yet\n"))
    popupmsg(_('Info'),_("Not implemented yet"))

#------------------------------------------------------------------------------
# Main program start - set TK GUI based on
# https://github.com/beenje/tkinter-logging-text-widget
# Copyright (c) 2017, Benjamin Bertrand
#------------------------------------------------------------------------------

LARGE_FONT = ("Verdana", 12)
NORM_FONT  = ("Helvetica", 10)
SMALL_FONT = ("Helvetica", 8)

logger = logging.getLogger(__name__)

class QueueHandler(logging.Handler):
    """Class to send logging records to a queue

    It can be used from different threads
    The ConsoleUi class polls this queue to display records in a ScrolledText widget
    """
    # Example from Moshe Kaplan: https://gist.github.com/moshekaplan/c425f861de7bbf28ef06
    # (https://stackoverflow.com/questions/13318742/python-logging-to-tkinter-text-widget) is not thread safe!
    # See https://stackoverflow.com/questions/43909849/tkinter-python-crashes-on-new-thread-trying-to-log-on-main-thread

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)


class ConsoleUi:
    """Poll messages from a logging queue and display them in a scrolled text widget"""

    def __init__(self, frame):
        self.frame = frame
        # Create a ScrolledText wdiget
        self.scrolled_text = ScrolledText(frame, state='disabled', height=12)
        self.scrolled_text.grid(row=0, column=0, sticky=(N, S, W, E),padx=3,pady=3)
        self.scrolled_text.configure(font='TkFixedFont')
        self.scrolled_text.tag_config('INFO', foreground='black')
        self.scrolled_text.tag_config('DEBUG', foreground='gray')
        self.scrolled_text.tag_config('WARNING', foreground='orange')
        self.scrolled_text.tag_config('ERROR', foreground='red')
        self.scrolled_text.tag_config('CRITICAL', foreground='red', underline=1)
        # Create a logging handler using a queue
        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        #formatter = logging.Formatter('%(asctime)s: %(message)s')
        formatter = logging.Formatter('%(message)s')
        self.queue_handler.setFormatter(formatter)
        logger.addHandler(self.queue_handler)
        # Start polling messages from the queue
        self.frame.after(100, self.poll_log_queue)

    def display(self, record):
        msg = self.queue_handler.format(record)
        self.scrolled_text.configure(state='normal')
        self.scrolled_text.insert(tk.END, msg + '\n', record.levelname)
        self.scrolled_text.configure(state='disabled')
        # Autoscroll to the bottom
        self.scrolled_text.yview(tk.END)

    def poll_log_queue(self):
        # Check every 100ms if there is a new message in the queue to display
        while True:
            try:
                record = self.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                self.display(record)
        self.frame.after(100, self.poll_log_queue)


class FormUi:

    def __init__(self, frame):
        self.frame = frame
        # Create a combobbox to select the logging level
        values = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        self.level = tk.StringVar()
        ttk.Label(self.frame, text=_('Level:')).grid(column=0, row=0, sticky=W, padx=3, pady=3)
        self.combobox = ttk.Combobox(
            self.frame,
            textvariable=self.level,
            width=25,
            state='readonly',
            values=values
        )
        self.combobox.current(0)
        self.combobox.grid(column=1, row=0, sticky=(W, E), padx=3, pady=3)
        # Create a text field to enter a message
        self.message = tk.StringVar()
        ttk.Label(self.frame, text=_('Message:')).grid(column=0, row=1, sticky=W, padx=3, pady=3)
        ttk.Entry(self.frame, textvariable=self.message, width=25).grid(column=1, row=1, sticky=(W, E), padx=3, pady=3)
        # Add a button to log the message
        self.button = ttk.Button(self.frame, text=_('Submit'), command=self.submit_message)
        self.button.grid(column=1, row=2, sticky=W, padx=3, pady=3)

    def submit_message(self):
        # Get the logging level numeric value
        lvl = getattr(logging, self.level.get())
        logger.log(lvl, self.message.get())


class RouterInfo:
    def __init__(self, frame):
        global rtr_hwversion
        global rtr_manufacturer
        global rtr_modelname
        global rtr_serial
        global rtr_fwupgrade
        global rtr_customerid
        global rtr_bsdgui
        global rtr_fwdowngrade
        global rtr_ip
        global rtr_mask
        global rtr_rwebgui
        global rtr_rcli
        global rtr_fixddns
        
        self.frame = frame
        ttk.Label(self.frame, text=_('Hardware Version: ')).grid(column=0, row=1, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_hwversion).grid(column=1, row=1, sticky=W)

        ttk.Label(self.frame, text=_('Manufacturer: ')).grid(column=0, row=2, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_manufacturer).grid(column=1, row=2, sticky=W)
        
        ttk.Label(self.frame, text=_('Model Name: ')).grid(column=0, row=3, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_modelname).grid(column=1, row=3, sticky=W)

        ttk.Label(self.frame, text=_('Router customer ID: ')).grid(column=0, row=4, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_customerid).grid(column=1, row=4, sticky=W)
        
        ttk.Label(self.frame, text=_('Serial Number: ')).grid(column=0, row=5, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_serial).grid(column=1, row=5, sticky=W)

        ttk.Label(self.frame, text=_('Router IP (bridge interface): ')).grid(column=0, row=6, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_ip).grid(column=1, row=6, sticky=W)
        
        ttk.Label(self.frame, text=_('Router Net Mask (bridge interface): ')).grid(column=0, row=7, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_mask).grid(column=1, row=7, sticky=W)

        ttk.Label(self.frame, text=_('BSD GUI visible: ')).grid(column=0, row=8, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_bsdgui).grid(column=1, row=8, sticky=W)
        
        ttk.Label(self.frame, text=_('Restricted web GUI: ')).grid(column=0, row=9, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_rwebgui).grid(column=1, row=9, sticky=W)

        ttk.Label(self.frame, text=_('Restricted CLI commands: ')).grid(column=0, row=10, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_rcli).grid(column=1, row=10, sticky=W)
        
        ttk.Label(self.frame, text=_('Firmware upgrade enabled: ')).grid(column=0, row=11, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_fwupgrade).grid(column=1, row=11, sticky=W)
        
        ttk.Label(self.frame, text=_('Firmware downgrade enabled: ')).grid(column=0, row=12, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_fwdowngrade).grid(column=1, row=12, sticky=W)
        
        ttk.Label(self.frame, text=_('Fix dlinkdns -> dlinkddns: ')).grid(column=0, row=13, sticky=W)
        ttk.Label(self.frame, textvariable=rtr_fixddns).grid(column=1, row=13, sticky=W)
        
class ThirdUi:

    def __init__(self, frame):
        global xml_src_lbl
        global cpexml_src_lbl
        self.frame = frame
        ttk.Label(self.frame, text=_('Main configuration file (XML): ')).grid(column=0, row=1, sticky=W)
        ttk.Label(self.frame, textvariable=xml_src).grid(column=1, row=1, sticky=W)

        ttk.Label(self.frame, text=_('CPE configuration file (XML) : ')).grid(column=0, row=2, sticky=W)
        ttk.Label(self.frame, textvariable=cpexml_src).grid(column=1, row=2, sticky=W)


class App:

    def __init__(self, root):
        global filem
        global infom
        global editm
        self.root = root
        root.title(_('ADB Config Editor'))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        # Create the panes and frames
        vertical_pane = ttk.PanedWindow(self.root, orient=VERTICAL)
        vertical_pane.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        horizontal_pane = ttk.PanedWindow(vertical_pane, orient=HORIZONTAL)
        vertical_pane.add(horizontal_pane)
        form_frame = ttk.Labelframe(horizontal_pane, text=_("Router Info"))
        form_frame.columnconfigure(1, weight=1, minsize=120)
        horizontal_pane.add(form_frame, weight=1)
        console_frame = ttk.Labelframe(horizontal_pane, text=_("Console"))
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)
        horizontal_pane.add(console_frame, weight=1)
        third_frame = ttk.Labelframe(vertical_pane, text=_("Configuration loading status"))
        vertical_pane.add(third_frame, weight=1)
        # Initialize all frames
        self.form = RouterInfo(form_frame)
        self.console = ConsoleUi(console_frame)
        self.third = ThirdUi(third_frame)
        #self.clock = Clock()
        #self.clock.start()
        self.root.protocol('WM_DELETE_WINDOW', self.quit)
        self.root.bind('<Control-q>', self.quit)
        signal.signal(signal.SIGINT, self.quit)

        menubar = Menu(root)
        root.config(menu=menubar)

        filem = Menu(menubar)
        filem.add_command(label = _('Open configuration file (BIN format)'),        command = load_config)
        filem.add_command(label = _('Open configuration file (XML format)'),        command = load_xmlconfig)
        filem.add_command(label = _('Open CPE configuration file (XML format)'),    command = load_cpexmlconfig)
        filem.add_command(label = _('Save configuration file (BIN format)'),        command = save_config, state = DISABLED)
        filem.add_command(label = _('Save configuration file (XML format)'),        command = save_xmlconfig, state = DISABLED)
        filem.add_command(label = _('Save CPE configuration file (XML format)'),    command = save_cpexmlconfig, state = DISABLED)
        filem.add_command(label = _('Exit'),                                        command = confquit)        
        menubar.add_cascade(label = _('File'), menu = filem)

        infom = Menu(menubar)
        infom.add_command(label = _('Show passwords'),           command = print_passwords, state = DISABLED)
        infom.add_command(label = _('Show restricted commands'), command = show_restricted, state = DISABLED)
        infom.add_command(label = _('Save passwords'),           command = save_passwords, state = DISABLED)
        infom.add_command(label = _('Save restriced commands'),  command = save_restricted, state = DISABLED)
        infom.add_command(label = _('Info about program'),                    command = about)
        menubar.add_cascade(label = _('Info'), menu = infom)

        editm = Menu(menubar)
        editm.add_command(label = _('Unlock restricted web GUI'),         command = enable_restricted_web, state = DISABLED)
        editm.add_command(label = _('Unlock restricted CLI commands'),    command = enable_restricted_cli, state = DISABLED)
        editm.add_command(label = _('Enable firmware upgrade/downgrade'), command = enable_fw_upgrade, state = DISABLED)
        editm.add_command(label = _('Fix dlinkdns -> dlinkddns'),         command = fix_dlinkddns, state = DISABLED)        
        editm.add_command(label = _('Settings'),                          command = edit_preference)        
        menubar.add_cascade(label = _('Edit'), menu = editm)

        
    def quit(self, *args):
        #self.clock.stop()
        self.root.destroy()
# def popup_bonus():
#     win = tk.Toplevel()
#     win.wm_title("Window")
    
#     l = tk.Label(win, text="Input")
#     l.grid(row=0, column=0)
    
#     b = ttk.Button(win, text="OK", command=win.destroy)
#     b.grid(row=1, column=0)
                            
        
def popupmsg(title,msg):
    popup = tk.Toplevel()
    popup.wm_title(title)
    popup.columnconfigure(0, weight=1, minsize=150, pad=15)
    popup.rowconfigure(0, weight=1, minsize=50)
    l = ttk.Label(popup, text=msg, font=NORM_FONT)
    l.grid(row=0, column=0, padx=3, pady=3)
    b = ttk.Button(popup, text=_("OK"), command = popup.destroy)
    b.grid(row=1,column=0, padx=3, pady=3)
    # Gets the requested values of the height and widht.
    windowWidth = popup.winfo_reqwidth()
    windowHeight = popup.winfo_reqheight()
    print("Width",windowWidth,"Height",windowHeight)

    # Gets both half the screen width/height and window width/height
    positionRight = int(popup.winfo_screenwidth()/2 - windowWidth/2) - 300 + 100
    positionDown = int(popup.winfo_screenheight()/2 - windowHeight/2) + 100
    
    # Positions the window in the center of the page.
    popup.geometry("+{}+{}".format(positionRight, positionDown))
    

def edit_preference():
    global iniconfig
    global dbginfo
    global popup
    global lastloc
    global dirloc
    global e2
    global prefinprog
    global language

    avail_languages = ['en']
    locale_files = os.listdir(mydir + '/locale/')
    for i in locale_files:
        if os.path.isdir((mydir + '/locale/' + i)):
            logger.log (ldebug, _("Available language: ") + i)
            avail_languages.append(i)
    
    popup = tk.Toplevel()
    popup.wm_title('Edit Preference')
    popup.columnconfigure(0, weight=1, minsize=150, pad=15)
    popup.rowconfigure(0, weight=1, minsize=50)
    dbginfo = StringVar(popup)
    dbginfo.set(iniconfig['global']['LogDebug'])
    lastloc = StringVar(popup)
    lastloc.set(iniconfig['global']['SaveLoadDirLastLocation'])
    dirloc  = StringVar(popup)
    dirloc.set(iniconfig['global']['SaveLoadDir'])
    prefinprog = StringVar(popup)
    try:
        prefinprog.set(iniconfig['global']['PreferenceInProgramFolder'])
    except:
        if os.path.isfile(proginifile):
            iniconfig['global'] = {'PreferenceInProgramFolder': 'yes'}
        else:
            iniconfig['global'] = {'PreferenceInProgramFolder': 'no'}
        prefinprog.set(iniconfig['global']['PreferenceInProgramFolder'])
    
    if (lastloc.get() == 'yes'):
        dirloc.set(defaultdir)

    language = StringVar(popup)
    try:
        language.set(iniconfig['global']['Language'])
    except:
        iniconfig['global'] = {'Language': language_default()}
        language.set(iniconfig['global']['Language'])
    
    c0 = ttk.Checkbutton(popup, text=_("Print debugging info"),
                         variable=dbginfo, onvalue='yes', offvalue='no')
    c0.grid(row=0, column=0, columnspan=2, padx=3, pady=0, sticky='W')

    c1 = ttk.Checkbutton(popup,text=_("Use last used folder as load/save location"),
                         variable=lastloc, onvalue='yes', offvalue='no', command=edit_pref_dirloc)
    c1.grid(row=1, column=0, columnspan=2, padx=3, pady=0, sticky='W')

    l2 = ttk.Label(popup, text=_("Save/Load default folder"))
    l2.grid(row=2, column=0, padx=3, pady=0, sticky='W')
    
    e2 = ttk.Entry(popup, textvariable=dirloc, width=len(dirloc.get()) + 15, state=DISABLED)
    e2.grid(row=2, column=1, padx=3, pady=0, sticky='W')

    c3 = ttk.Checkbutton(popup, text=_("Preference file in program folder instead of user's folder"),
                         variable=prefinprog, onvalue='yes', offvalue='no')
    c3.grid(row=3, column=0, columnspan=2, padx=3, pady=0, sticky='W')

    
    l4 = ttk.Label(popup, text=_("Default Language (restart needed after change)"))
    l4.grid(row=4, column=0, padx=3, pady=0, sticky='W')
    
    cb4 = ttk.Combobox(popup, textvariable=language, value=avail_languages, state='readonly', width=5)
    cb4.grid(row=4, column=1, padx=3, pady=0, sticky='W')
    
    bend = ttk.Button(popup, text=_("Cancel"), command = popup.destroy)
    bend.grid(row=5,column=0, padx=30, pady=3, sticky='W')

    bendb = ttk.Button(popup, text=_("Save"), command = save_preference)
    bendb.grid(row=5,column=1, padx=30, pady=3, sticky='E')

	
    # Gets the requested values of the height and widht.
    windowWidth = popup.winfo_reqwidth()
    windowHeight = popup.winfo_reqheight()
    print("Width",windowWidth,"Height",windowHeight)

    # Gets both half the screen width/height and window width/height
    positionRight = int(popup.winfo_screenwidth()/2 - windowWidth/2) - 300 + 100
    positionDown = int(popup.winfo_screenheight()/2 - windowHeight/2) + 100
    
    # Positions the window in the center of the page.
    popup.geometry("+{}+{}".format(positionRight, positionDown))
    print("dbginfo: " + dbginfo.get())

def edit_pref_dirloc():
    global popup
    global dirloc
    global lastloc
    global e2
    global defaultdir
    global prefinprog
	
    if (lastloc.get() == 'yes'):
        e2.configure(state=DISABLED)
        dirloc.set(defaultdir)
    else:
        e2.configure(state=NORMAL)
		 
def save_preference():
    global popup
    global iniconfig
    global dbginfo
    global lastloc
    global dirloc
    global inifile
    global language
    
    iniconfig['global']['LogDebug']=dbginfo.get()
    iniconfig['global']['SaveLoadDirLastLocation']=lastloc.get()
    iniconfig['global']['PreferenceInProgramFolder']=prefinprog.get()
    iniconfig['global']['Language']=language.get()
    language_set(language.get())

    if iniconfig['global']['LogDebug'] == 'yes':
        #logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    else:
        #logging.basicConfig(level=logging.INFO)
        logger.setLevel(logging.INFO)
        
    if iniconfig['global']['PreferenceInProgramFolder'] == 'yes':
        inifile = proginifile
        if os.path.isfile(userinifile):
            logger.log(linfo,_("Removing user's preference file ") + userinifile)
            try:
                os.remove(userinifile)
            except:
                logger.log(lerr,_("Error removing ") + userinifile)
    else:
        inifile = userinifile
        if os.path.isfile(proginifile):
            logger.log(linfo,_("Removing preference file in program folder: ") + proginifile)
            try:
                os.remove(proginifile)
            except:
                logger.log(lerr,_("Error removing ") + proginifile)
                
    if (os.path.isdir(dirloc.get())):
        iniconfig['global']['SaveLoadDir']=dirloc.get()
        popup.destroy()
        write_inifile()
    else:
        popupmsg(_("Folder name error"),_("Folder not available: ") + dirloc.get())

                
def save_defaultdir():
    global iniconfig
    global defaultdir
    if (iniconfig['global']['SaveLoadDirLastLocation'] == 'yes') and \
       (iniconfig['global']['SaveLoadDir'] != defaultdir):
       iniconfig['global']['SaveLoadDir'] = defaultdir
       write_inifile()
                                
def print_passwords():
    global data_out
    global cpedata_out
    if (('data_out' in globals()) and ((loaded_bin == 1) or (loaded_xml == 1))):
        logger.log(lerr,"\n" + _("---- Passwords from main configuration file ----"))
        logger.log(lwarn,get_passwords(data_out))
    else:
        logger.log(lerr,"\n" + _("---- Main configuration file not loaded ----"))

    if (('cpedata_out' in globals()) and ((loaded_bin == 1) or (loaded_cpe == 1))):
        logger.log(lerr,_("---- Passwords from CPE configuration file ----"))
        logger.log(lwarn,get_passwords(cpedata_out))
    else:
        logger.log(lerr,"\n"+ _("---- CPE configuration file not loaded ----"))
        
#-----------------------------------------------------------------------------------------------
# save_passwords  - save passwords to a text file
#-----------------------------------------------------------------------------------------------
def save_passwords():
    global data_out
    global cpedata_out
    global defaultdir
    
    pass_str = ''
    if (('data_out' in globals()) and ((loaded_bin == 1) or (loaded_xml == 1))):
        pass_str = pass_str + _("---- Passwords from main configuration file ----") + "\n\n"
        pass_str = pass_str + get_passwords(data_out)
    else:
        pass_str = pass_str + _("---- Main configuration file not loaded ----") + "\n\n"

    if (('cpedata_out' in globals()) and ((loaded_bin == 1) or (loaded_cpe == 1))):
        pass_str = pass_str + "\n" + _("---- Passwords from CPE configuration file ----") + "\n\n"
        pass_str = pass_str + get_passwords(cpedata_out)
    else:
        pass_str = pass_str + "\n" + _("---- CPE configuration file not loaded ----") + "\n"
        
    name = asksaveasfilename(initialdir=defaultdir,
                             filetypes =((_("Text password file"), "*.txt"),(_("All Files"),"*.*")),
                             title = _("Choose a file")
                             )
    print (name)
    #Using try in case user types in unknown file or closes without choosing a file.
    try:
        with open(name,'w') as f:
            f.write(pass_str)
    except:
        print(_("Error writing "),name)
        sys.exit(1)

    defaultdir=os.path.dirname(name)

        
#-----------------------------------------------------------------------------------------------
# Main Program
#-----------------------------------------------------------------------------------------------



ldebug = logging.DEBUG
linfo  = logging.INFO
lwarn  = logging.WARNING
lerr   = logging.ERROR
lcri   = logging.CRITICAL

if os.path.isfile(mydir + '/.confedit.ini'):     # confed.ini can be stored in program folder based on user preferences
    logger.log(linfo,"Preference file in program folder")
    inidir  = mydir
    inifile = mydir + '/.confedit.ini'

read_inifile()

language_set(language_default())

if iniconfig['global']['LogDebug'] == 'yes':
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)
    
root = tk.Tk()

xml_src          = tk.StringVar()     # file loaded with main xml configuration
cpexml_src       = tk.StringVar()     # file loaded with cpe xml configuration
rtr_hwversion    = tk.StringVar()
rtr_manufacturer = tk.StringVar()
rtr_modelname    = tk.StringVar()
rtr_serial       = tk.StringVar()
rtr_fwupgrade    = tk.StringVar()
rtr_customerid   = tk.StringVar()
rtr_bsdgui       = tk.StringVar()
rtr_fwdowngrade  = tk.StringVar()
rtr_ip           = tk.StringVar()
rtr_mask         = tk.StringVar()
rtr_rwebgui      = tk.StringVar()
rtr_rcli         = tk.StringVar()
rtr_fixddns      = tk.StringVar()

rtr_hwversion.set(blank20)
rtr_manufacturer.set(blank20)
rtr_modelname.set(blank20)
rtr_serial.set(blank20)
rtr_fwupgrade.set(blank20)
rtr_customerid.set(blank20)
rtr_bsdgui.set(blank20)
rtr_fwdowngrade.set(blank20)
rtr_ip.set(blank20)
rtr_mask.set(blank20)
rtr_rwebgui.set(blank20)
rtr_rcli.set(blank20)
rtr_fixddns.set(blank20)

xml_src.set(_('not loaded'))
cpexml_src.set(_('not loaded'))


app = App(root)


level=ldebug
logger.log(ldebug,_("mydir:      ") + mydir)
logger.log(ldebug,_("down_pem:   ") + up_pem)
logger.log(ldebug,_("tmpradix:   ") + tmpradix)
logger.log(ldebug,_("tmpconf:    ") + tmpconf)
logger.log(ldebug,_("tmpconfcpe: ") + tmpconfcpe)
logger.log(ldebug,_("homedir:    ") + homedir)
logger.log(ldebug,_("inifile:    ") + inifile)
logger.log(ldebug, _('Default language: ') + language_default())

# ---- center the main window
# Gets the requested values of the height and widht.
windowWidth = app.root.winfo_reqwidth()
windowHeight = app.root.winfo_reqheight()
print("Width",windowWidth,"Height",windowHeight)

# Gets both half the screen width/height and window width/height
positionRight = int(app.root.winfo_screenwidth()/2 - windowWidth/2) - 300
positionDown = int(app.root.winfo_screenheight()/2 - windowHeight/2)

# Positions the window in the center of the page.
app.root.geometry("+{}+{}".format(positionRight, positionDown))

app.root.mainloop()
save_defaultdir()

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------

