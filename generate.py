#!/usr/local/bin/python

import shutil, os, re 
import sqlite3

import json
import requests

from markdown import markdown
from cgi import escape


from templates import indexTemplate, pkgTemplate, moduleTemplate, toHtml
import string 

opj = os.path.join

pkgsURL = "http://package.elm-lang.org/"
rexp = re.compile("(.*)\n@docs\\s+([a-zA-Z0-9_']+(?:,\\s*[a-zA-Z0-9_']+)*)")


# cleanup and preparation
def prepare():

    global docpath, db, cur

    print("cleanig up..."), 
    
    if os.path.exists("./Elm.docset"):
        shutil.rmtree("./Elm.docset")

    resPath = "./Elm.docset/Contents/Resources/"
    

    docpath = opj(resPath, 'Documents')
    os.makedirs(docpath)
    files = [
        ("icon.png", "./Elm.docset/"),
        ("Info.plist", "./Elm.docset/Contents/"),
        ("style.css", "./Elm.docset/Contents/Resources/Documents/"),
        ("github.css", "./Elm.docset/Contents/Resources/Documents/"),
        ("highlight.pack.js", "./Elm.docset/Contents/Resources/Documents/"),
        ]
    for (fn, dest) in files:
        shutil.copyfile("./assetts/"+fn, dest+fn)
    

    db = sqlite3.connect(opj(resPath, 'docSet.dsidx'))
    cur = db.cursor()

    try: cur.execute('DROP TABLE searchIndex;')
    except: pass
    cur.execute('CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT);')
    cur.execute('CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path);')

    print("DONE!")

class Type(object):
    def __init__(self, json):
        self.name = json["name"]
        self.comment = json['comment']
        self.args = json["args"]
        self.cases = json["cases"]
     
    def get_markdown(self):
        ret = ['<div style="padding: 0px; margin: 0px; width: 980px; height: 1px; background-color: rgb(216, 221, 225);"></div>']

        ret.append(name_link(self.name))        

        ret.append(self.comment)
        return "\n\n".join(ret)

    markdown = property(get_markdown)


class Alias(object):
    def __init__(self, json):
        self.name = json["name"]
        self.comment = json['comment']
        self.args = json["args"]
        self.type = json["type"]
    
    def get_markdown(self):
        ret = ['<div style="padding: 0px; margin: 0px; width: 980px; height: 1px; background-color: rgb(216, 221, 225);"></div>']

        ret.append(name_link(self.name))        
        
        ret.append(self.comment)
        return "\n\n".join(ret)

    markdown = property(get_markdown)


valid_chars = "_'"+string.digits+string.lowercase+string.uppercase

def name_link(name):
    safe_name = escape(name if name[0] in valid_chars else "(%s)"%name)
    return '<strong> <a class="mono" name="%s" href="#%s">%s</a> <span class="green"> :</span> </strong>'%(name, name, safe_name)

class Value(object):
    def __init__(self, json):
        self.name = json["name"]
        self.comment = json['comment']
        self.type = json["type"]
        if "precedence" in json:
            self.assocPrec = (json["associativity"], json["precedence"])
        else:
            self.assocPrec = None
    
    def get_markdown(self):
        ret = ['<div style="padding: 0px; margin: 0px; width: 980px; height: 1px; background-color: rgb(216, 221, 225);"></div>']
        
        try: 
            bits =  self.type.split("->")
        except:
            bits = [] # dict received
        
        ret.append(name_link(self.name)+'<span class="mono">'+'<span class="green">-&gt;</span>'.join(bits)+"</span>")   
        if self.assocPrec:
            ret.append ("associativity: %s / precedence: %d"%self.assocPrec)

        ret.append(self.comment)

        return "\n\n".join(ret)

    markdown = property(get_markdown)

class Module(object):
    def __init__(self, json, package):
        self.package = package
        self.name = json["name"]
        self.comment = json['comment']
        self.aliases = {v.name:v for v in map(Alias, json['aliases'])}
        self.types = {v.name:v for v in map(Type, json['types'])}
        self.values = {v.name:v for v in map(Value, json['values'])}

    def insert_in_db(self, name, kind):
        file_name = docname(self.package, self.name)
        cur.execute('INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)', (name, kind, file_name+"#"+name))
    
    def get_markdown(self):
        pre = self.comment.split("#")[0]
        body = self.comment[len(pre):]


        ret = [pre]
        try:
            for part in body.split("#"):
                if part:
                    title = "# "+ part.splitlines()[0]
                    ret.append(title)       

                    content = "\n".join(part.splitlines()[1:])

                    if "@" in content:
                        comment, hints = content.split("@")
                        
                        if comment.strip() : ret.append(comment)
                        
                        items = [i.strip() for i in hints.split(",")]
                        
                        for item in items:
                            if item.startswith("docs"): item = item.split()[1]
                            if item.startswith("("): item = item[1:-1]

                            if item in self.values:
                                
                                self.insert_in_db(self.values[item].name, "Function")
                                ret.append(self.values[item].markdown)

                            elif item in self.types:
                                
                                self.insert_in_db(self.types[item].name, "Union")
                                ret.append(self.types[item].markdown)

                            elif item in self.aliases:
                                
                                self.insert_in_db(self.aliases[item].name, "Type")

                                ret.append(self.aliases[item].markdown)
                    else:
                        ret.append(content)
        except:
            print "Error in ", self.package, self.name

        return  "\n\n".join(ret)

    markdown = property(get_markdown)

def docname(pkg, module=None):
    module = (module if module else "index")
    return ".".join([pkg.replace("/", "."), module, "html"])

def generate_all():
    global pkgs
    print("feching all packages list ..."),
    all_pkgs = requests.get(pkgsURL+"all-packages").json()
    print("DONE!")
    print("feching new packages list ..."),
    new_pkgs = requests.get(pkgsURL+"new-packages").json()
    print("DONE!")

    new_pkgs = list(set(new_pkgs))
    all_pkgs_dict = {p["name"]:p for p in all_pkgs}

    deprecated = [p for p in all_pkgs_dict.iteritems() if not p in new_pkgs]

    pkgs = [p for p in all_pkgs if  p["name"] in new_pkgs]
    pkgs.sort(key=lambda a: a["name"].lower())
    
    # generate the index
    with open(opj(docpath, "index.html"), "w") as fo:
        fo.write(indexTemplate({"pkgs":[(pkg["name"], docname(pkg["name"]), pkg["summary"]) for pkg in pkgs]}))

    no_pkgs = len(pkgs)
    for pkg in pkgs:
        idx = pkgs.index(pkg)+1
        pkg_name = pkg["name"]
        pkg_file = docname(pkg_name)
        pkg_version = pkg["versions"][0]
        print "Generating package: "+pkg_name+" [% 3d / %03d]..."%(idx, no_pkgs), 

        docURL = pkgsURL+"/".join(["packages", pkg_name, pkg_version, "documentation"])+".json"
        json = requests.get(docURL).json()
        # module = Module(json)
        links = []
        for module in json:
            module = Module(module, pkg_name)
            module_file = docname(pkg_name, module.name)
            links.append((module.name, module_file))
            with open(opj(docpath, module_file), "w") as fo:  
                html = toHtml(module.markdown).replace('<code>', '<code class="elm">') # fix syntax detection
                data = { "pkg_link": (pkg_name, pkg_file), "module_name":module.name, "markdown":html}
                fo.write(moduleTemplate(data))
            cur.execute('INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)', (module.name, 'Module', module_file))

        with open(opj(docpath, pkg_file), "w") as fo:
            data = { "pkg_name": pkg_name, "modules":links, "version":pkg_version}
            fo.write(pkgTemplate(data))
        cur.execute('INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?,?,?)', (pkg_name, 'Package', pkg_file))

        print "DONE!"

DEBUG = False 
# DEBUG = True

if __name__ == '__main__':
    print("starting ...")

    if DEBUG:
        from debug import debug_module
        debug_module("circuithub/elm-bootstrap-html", "Bootstrap.Html")
    else:
        prepare()

        generate_all()
        
        db.commit()
        db.close()

    print("Alright! Take Care Now, Bye Bye Then!")