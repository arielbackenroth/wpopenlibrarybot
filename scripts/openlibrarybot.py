#!/usr/bin/env python

import csv, re
from wikitools import wiki, page, api
from optparse import OptionParser

EDIT_COMMENT = "[[Wikipedia:Bots/Requests for approval/OpenlibraryBot|discuss this trial]]"

def insert_link_into_wikitext(link, wikitext):
    def generate_wikitext(lines):
        assert re.match('==\s*External links\s*==', lines[0].strip()), lines[0]
        yield lines[0]

        emptylines = []
        inserted = False
        insertable = False

        for line in lines[1:]:
            if inserted:
                # the link has been inserted - just flush remaining lines
                yield line
            elif line.strip().startswith("*"):
                # we're in something that looks like a list - we can insert the link
                # at the end
                insertable = True
                for el in emptylines:
                    yield el
                emptylines = []
                yield line
            elif not line.strip():
                # preserve whitespace
                emptylines.append(line)
            elif insertable:
                # it's not whitespace or a link - it's something else.  let's insert here
                # and then push back any whitespace
                yield "* %s" % link
                for el in emptylines:
                    yield el
                emptylines = []
                yield line
                inserted = True
            else:
                # this might be another macro like {{Wikiquotes}} - just ignore
                for el in emptylines:
                    yield el
                emptylines = []
                yield line
        
        if not inserted and insertable:
            # the list just ended without a newline - yield the link
            yield "* %s" % link
                
    return '\n'.join(list(generate_wikitext(wikitext.split('\n'))))

if __name__ == "__main__":
    parser = OptionParser(usage="%prog [-u bot_username] [-p bot_password] file")
    parser.add_option("-u", "--bot-username", dest="bot_username", 
                      default="OpenlibraryBot",
                      help="The bot username for writing to wikipedia")
    parser.add_option("-p", "--bot-password", dest="bot_password", 
                      help="The bot password for writing to wikipedia")

    options, args = parser.parse_args()
    if len(args) != 1:
        parser.error("file required")

    if not options.bot_password:
        parser.error("bot password required")
        
    site = wiki.Wiki("http://en.wikipedia.org/w/api.php")
    site.login(options.bot_username, options.bot_password)

    def add_link(wpid, olid, type):
        p = page.Page(site, pageid=wpid)
        link_template = {
            "/type/author": "OL_author",
            "/type/work": "OL_work",
            "/type/book": "OL_book"
        }[type]
        if not p.setSection(section="External links"):
            print "%s (%s) has no external links, skipping" % (p.title, wpid)
            return
        
        old_wt = p.getWikiText()
        existing = re.search("{{%s\|?[\w].+}}" % link_template, old_wt)
        if existing:
            print "%s (%s) already has a link %s, skipping" % (p.title, wpid, existing.group())
            return

        new_wt = insert_link_into_wikitext("{{%s|id=%s}}" % (link_template, olid), old_wt)
        if old_wt != new_wt:
            result = p.edit(bot=True, summary=EDIT_COMMENT, text=new_wt)
            assert result['edit']['result'].lower() == 'success'
            print "added %s(%s) to %s (%s)" % (link_template, olid, p.title, wpid)

    # args[0] is a tsv of [wikipediaid|openlibraryid|openlibrary_type|name (for debugging)]
    f = open(args[0])
    with f:
        data = csv.reader(f, delimiter='\t')
    
        for wpid, olid, type, name in data:
            add_link(wpid, olid, type)
