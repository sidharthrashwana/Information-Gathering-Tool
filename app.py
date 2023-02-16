from datetime import datetime
import time
from flask import Flask,redirect,render_template,request,session,jsonify,render_template_string,url_for,send_from_directory
import json
import os
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
import smtplib
import requests
from googleapiclient.discovery import build
import socket
import folium
from itertools import groupby
from threading import Thread
import os
from flask_dance.contrib.google import make_google_blueprint, google
import re
from flask_login import logout_user
import requests
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
###########################################################################Initialize Variables###########################################################################

basedir=os.path.abspath(os.path.dirname(__file__))
filename='config.json'
print(basedir)
with open(filename,'r', encoding='utf-8') as f:
    params = json.load(f)['params']
    #print(params)

#if run on localhost , set local_server=True
local_server=True
app = Flask(__name__)
csrf = CSRFProtect()
csrf.init_app(app)
app.secret_key=params['secret-key']

#connect based on localhost or production environment
if local_server:
    app.config['SQLALCHEMY_DATABASE_URI'] = params['local_uri']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = params['prod_uri']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True

#google search API parameters
API_KEY = '<API-KEY>'#to be able to search on google
CSE_ID = '<CSE_ID'#in order to make your search queries
path=basedir+'/software/dnsrecon/dnsrecon.py'
dictionary=basedir+'/software/dnsrecon/subdomains-top1mil-20000.txt'
ip_address=''

##########################################################OAUTH######################################################################################
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = '1'
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = '1'

blueprint = make_google_blueprint(
    client_id="<client-id-from-developer-console>",
    client_secret="<client-secret-key-from-developer-console>",
    # reprompt_consent=True,
    offline=True,
    scope=["profile", "email"],
)
app.register_blueprint(blueprint, url_prefix="/login")
"""
@app.route('/welcome')
def welcome():
    resp = google.get("/oauth2/v2/userinfo")
    assert resp.ok, resp.text
    email=resp.json()["email"]

    return render_template("welcome.html",email=email)
"""
blueprint.from_config["session.client_id"] = "GOOGLE_OAUTH_CLIENT_ID"

@app.route("/login/google")
def login():
    if not google.authorized:
        return render_template(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    assert resp.ok, resp.text
    email=resp.json()["email"]
    return render_template("/session/dashboard.html",email=email)

###########################################################################Database############################################################################
#make connection to DB
db = SQLAlchemy(app)

#to receive email in mail as well
server=smtplib.SMTP('smtp.gmail.com',587)
server.starttls()
server.login(params['gmail-user'],params['gmail-pass'])

#create structure same as backend DB for 'user' table
class User(db.Model):
   serial = db.Column( db.Integer, primary_key = True)
   source_ip = db.Column(db.String(20),nullable=False)
   Location = db.Column(db.String(50),nullable=True)  
   date = db.Column(db.String(10),nullable=True)

#create structure same as backend DB for 'contact' table
class Contact(db.Model):
   serial = db.Column( db.Integer, primary_key = True)
   name = db.Column(db.String(20),nullable=False)
   subject = db.Column(db.String(50),nullable=False)
   email = db.Column(db.String(50),nullable=False)  
   message = db.Column(db.String(1000),nullable=False)
   date = db.Column(db.String(10),nullable=True)

@app.route("/contactInfo",methods=['GET','POST'])
def contactInfo():
    #to send encrypted string to email
    if(request.method == 'POST'):
        """Add entry to database"""
        name=request.form.get('name')
        email=request.form.get('email')
        subject=request.form.get('subject')
        msg=request.form.get('message')
        """ Insert into database
            LHS : database columns
            RHS: local variable
        """
        #contact table insertion
       
        entry=Contact(name=name,subject=subject,email=email,message=msg,date=datetime.now())
        db.session.add(entry)
        db.session.commit()
        data=name+'\n'+email+'\n'+subject+'\n'+msg+'\n'
        server.sendmail(params['gmail-user'],params['send_to'],data)
        print('Mail sent')
        server.sendmail(params['gmail-user'],str(email),'You email is received.')
        return render_template('/successful/message.html')
    else:
        return redirect('/')

#################################################################################################################################################################
#############################################################################Routes##############################################################################
#define routes
@app.route("/")
def Index(): 
    global resp
    #don't allow mobile devices
    user_agent=request.headers.get('User-Agent')
    print('user agent',user_agent)
    for device in ['iPhone', 'iPad','iphone','ipad', 'android','Android' ,'Windows Phone','Windows NT']:
        if device=='Windows NT' and device in user_agent:
            if 'Gecko/20100101' in user_agent:
                msg="Tor Browser is not allowed due to security reasons."
                return render_template('/authorization/device.html',msg=msg,device='Please access from a valid browser.')
        elif device in user_agent:
            msg="This web application is high end and meant only for computer users you are using %s."%(device)
            return render_template('/authorization/device.html',msg=msg,device="Please access from a valid resource.")
    #if not mobile devices
    resp = google.get("/oauth2/v2/userinfo")
    print(resp.text)
    if google.authorized :
        username=resp.json()["name"]
        if username:
            print(username)
            sourceIP=request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
            print(sourceIP)
            #user table insertion
            entry2=User(source_ip=sourceIP,date=datetime.now())
            db.session.add(entry2)
            db.session.commit()
            return render_template('/session/dashboard.html',username=username)
        else:
            msg="Please clear cache and re-login to the portal."
            render_template('/error/error.html',msg=msg)
    return render_template('index.html')

@app.route("/elements",methods=['GET', 'POST'])
def elements():
    global searchTerm,ip_address
    if google.authorized :
        print(ip_address)
        FileExists=os.popen(('ls %s')%(basedir+'/static/map/map.html')).read()
        #if file exists , then remove it
        if 'No such file' not in FileExists:
            os.popen('rm ~/project/project-x/static/map/map.html').read()
        if request.method == 'POST':
            searchTerm=request.form.get('search')
        #when we navigate back , then to avoid refetching the request
        ip_address=findIP(searchTerm)
        print(ip_address)
        if ip_address != -1:
            response = requests.get(f"https://ipapi.co/{ip_address}/json/?key=<add-your-key>").json()
            print(response)
            latitude= str(response.get("latitude"))
            longitude=str(response.get("longitude"))
            if latitude and longitude != 'None':
                location_data = {"ip": ip_address,"continent":response.get("continent"),"city": response.get("city"),"region": response.get("region"),"country": response.get("country_name"),"longitude": response.get("longitude"),"latitude": response.get("latitude"),
                "timezone": response.get("timezone"),"isp": response.get("isp"),"org": response.get("org"),"asn": response.get("asn"),"proxy": response.get("proxy"),"country_code": response.get("country_code"),
                "threat_level": response.get("threat_level")}
                print(location_data)
                mapConstruct(latitude,longitude)
                time.sleep(2)
                thread1=Thread(target=normal_dns)
                thread1.start()
                thread2 = Thread(target=indepth_dns)
                thread2.start()
                thread3 = Thread(target=scanReport)
                thread3.start()
                time.sleep(2)
                thread4 = Thread(target=vulnScan)
                thread4.start()
                time.sleep(2)
                thread5 = Thread(target=servScan)
                thread5.start()
                time.sleep(2)
                return render_template("/session/features.html",location=location_data)
            else:
                msg="Latitude or longitude not found due to invalid IP address or Rate Limit."
                return render_template('/error/error.html',msg=msg)
        else:
            msg="IP address is not found."
            return render_template('/error/error.html',msg=msg)
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)

@app.route("/map")
def mapDispay():
    if google.authorized :
        return render_template("/session/maplayout.html")
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)
    
def check_response(url):
    global urls
    response = requests.get(url)
    if response.status_code == 200:
        print(f'{url} found')
        urls.append(url)

##############################DNS#########################################
@app.route("/dns")
def dnsInfo():
    global dnsList
    if google.authorized :
        if dnsList != None:
            return render_template("/session/dnsInfo.html",dnsinfo=dnsList)
        else:
            return render_template("/session/dnsInfo.html",dnsinfo=None)
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)

@app.route("/depthdns")
def depthdnsInfo():
    global dnsEnum
    if google.authorized :
        if dnsEnum != None:
            return render_template("/session/dnsDepth.html",dnsinfo=dnsEnum)
        else:
            return render_template("/session/dnsDepth.html",dnsinfo=None)
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)

################################################ACTION#################################
###REPORT

@app.route("/reportRecon")
def reportRecon():
    global timestamp1
    if google.authorized :
        return send_from_directory("./reports/nmap/","%s.html"%(timestamp1))
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)

@app.route("/reportServ")
def reportServ():
    global timestamp2
    if google.authorized :
        #check if file exists
        return send_from_directory("./reports/nmap/","%s.html"%(timestamp2))
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)

@app.route("/reportVuln")
def reportVuln():
    global timestamp3
    if google.authorized :
        return send_from_directory("./reports/nmap/","%s.html"%(timestamp3))
    else:
        msg="You are not logged In."
        return render_template('/error/error.html',msg=msg)

#############################################LOGOUT #########################################
@app.route("/logout")
def logout():
    if google.authorized :
        token = blueprint.token["access_token"]
        resp=google.post('https://oauth2.googleapis.com/revoke',params={'token': token},
                    headers = {'content-type': 'application/x-www-form-urlencoded'})
        assert resp.ok, resp.text
        del blueprint.token  # Delete OAuth token from storage
        return redirect('/')
    else:
        msg='You are not logged In.'
        return render_template('/error/error.html',msg=msg)

##########################################################################Functions###################################################
##################NMAP######################
def scanReport():
    global searchTerm,res,timestamp1
    timestamp1=time.time()
    timestam1p=int(timestamp1)
    print(timestamp1)
    res=[]
    #kill all instances of the nmap
    os.popen('killall nmap')
    time.sleep(5)
    nmap=os.popen(("nmap -p1-65535 %s -vv -oX ./reports/nmap/%s")%(searchTerm,timestamp1)).read()
    for line in nmap.split("\n"):
        res.append(line)
    time.sleep(2)
    html=os.popen(("xsltproc  ./reports/nmap/%s -o ./reports/nmap/%s.html")%(timestamp1,timestamp1)).read()
    print(html)

def vulnScan():
    global searchTerm,vuln,timestamp2
    timestamp2=time.time()
    timestamp2=int(timestamp2)
    print(timestamp2)
    vuln=[]
    os.popen('killall nmap')
    time.sleep(5)
    nmap=os.popen(("nmap --script vuln -p1-65535 %s -vv -oX ./reports/nmap/%s")%(searchTerm,timestamp2)).read()
    for line in nmap.split("\n"):
        vuln.append(line)
    time.sleep(2)
    html=os.popen(("xsltproc  ./reports/nmap/%s -o ./reports/nmap/%s.html")%(timestamp2,timestamp2)).read()
    print(html)

def servScan():
    global searchTerm,serv,timestamp3
    timestamp3=time.time()
    timestamp3=int(timestamp3)
    print(timestamp3)
    serv=[]
    os.popen('killall nmap')
    time.sleep(5)
    nmap=os.popen(("nmap -p1-65535 -sV -sC %s -vv -oX ./reports/nmap/%s")%(searchTerm,timestamp3)).read()
    for line in nmap.split("\n"):
        serv.append(line)
    time.sleep(2)
    html=os.popen(("xsltproc  ./reports/nmap/%s -o ./reports/nmap/%s.html")%(timestamp3,timestamp3)).read()
    print(html)

##################DNS######################
def normal_dns():
    try:
        global searchTerm,dnsList
        dnsList=[]
        print(searchTerm)
        os.popen('killall dnsrecon')
        time.sleep(5)
        dns=os.popen(("dnsrecon -d %s")%(searchTerm)).read()
        print(dir(dns))
        for line in dns.split("\n"):
            if line not in dnsList:
                dnsList.append(line)
        #remove consecutive pattern
        dnsList=[i[0] for i in groupby(dnsList)]
        print(dnsList)
    except:
        normal_dns()

def indepth_dns():
    try:
        global searchTerm,dnsEnum
        dnsEnum=[]
        print(searchTerm)
        os.popen('killall dnsrecon')
        time.sleep(5)
        dns=os.popen(("dnsrecon -d %s -D %s -t std,rvl,brt,srv,axfr,bing,yand,crt,snoop,tld,zonewalk -v")%(searchTerm,dictionary)).read()
        for line in dns.split("\n"):
            if line not in dnsEnum:
                dnsEnum.append(line)
        #remove consecutive pattern
        dnsEnum=[i[0] for i in groupby(dnsEnum)]
        print(dnsEnum)
    except:
        indepth_dns()

##################SEARCH######################
def termSearch():
    searchTerm=request.form.get('search')
    print(searchTerm)
    service = build("customsearch", "v1", developerKey=API_KEY)
    response = service.cse().list(q=searchTerm, cx=CSE_ID).execute()
    json_object = json.dumps(response, indent = 4)
    print(json_object)
    return render_template_string("<h1>welcome </h1>")

def mapConstruct(lat,lon):
    map=folium.Map(location=[lat,lon],zoom_start=10,zoom_end=18,min_zoom=4)
    folium.CircleMarker(location=[lat,lon],radius=50,popup="Location").add_to(map)
    folium.Marker(location=[lat,lon],radius=50,popup="Location").add_to(map)
    map.save("./static/map/map.html")

def findIP(searchTerm):
    ## getting the IP address using socket.gethostbyname() method
    try:
        regex = "^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$"
        # pass the regular expression
        # and the string in search() method
        print(searchTerm)
        if(re.search(regex, searchTerm)):
            print("Valid Ip address")
            return searchTerm
        else:
            #take website name and return ip address
            ip_address = socket.gethostbyname(searchTerm)
            ## printing the hostname and ip_address
            print(f"IP Address: {ip_address}")
            return ip_address
    except:
        msg="provide a valid IP address or hostname"
        print(msg)
        return -1

def convertDictToList():
    global dirs
    fileobj=open("directory-list-2.3-medium.txt")
    dirs=[]
    for line in fileobj:
        dirs.append(line.strip())
    print(dirs)
    
##########################################################################Run application#####################################################################

if __name__ == '__main__':
    #convertDictToList()
    app.run(debug=True,port=params['flask_port'],host='0.0.0.0')
    ###############################################################################################
