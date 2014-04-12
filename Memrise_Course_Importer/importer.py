﻿# -*- coding: utf-8 -*-

import codecs
import os.path
import re
import httplib
import time
import urllib
import urllib2
import urlparse
import Memrise_Course_Importer.uuid
from anki.importing import TextImporter
from anki.importing.noteimp import NoteImporter, ForeignNote
from anki.media import MediaManager
from anki.stdmodels import addBasicModel
from aqt import mw
from aqt.qt import *
from BeautifulSoup import BeautifulSoup

class MemriseImporter(NoteImporter):
	def __init__(self, *args):
		NoteImporter.__init__(self, *args)
		self.initMapping()
		self.selectDeck = lambda deckName: None

	def setSelectDeckLambda(self, callback):
		if callable(callback):
			self.selectDeck = callback

	def fields(self):
		"Number of fields."
		return 2

	def noteFromFields(self, fields):
		note = ForeignNote()
		note.fields.extend([x.strip().replace("\n", "<br>") for x in fields])
		note.tags.extend(self.tagsToAdd)
		return note

	def loadCourseInfo(self):
		response = urllib2.urlopen(self.file)
		soup = BeautifulSoup(response.read())
		title = soup.find("h1", "course-name").string.strip()
		levelTitles = map(lambda x: x.string.strip(), soup.findAll("div", "level-title"))
		return title, levelTitles

	def getLevelUrl(self, levelNum):
		return u"{:s}{:d}".format(self.file, levelNum)

	def downloadWithRetry(self, url, tryCount):
		if tryCount <= 0:
			return ""

		try:
			return urllib2.urlopen(url).read()
		except httplib.BadStatusLine:
			# not clear why this error occurs (seemingly randomly),
			# so I regret that all we can do is wait and retry.
			time.sleep(0.1)
			return self.downloadWithRetry(url, tryCount-1)

	def downloadMedia(self, url):
		# Replace links to images and audio on the Memrise servers
		# by downloading the content to the user's media dir
		mediaDirectoryPath = MediaManager(self.col, None).dir()
		memrisePath = urlparse.urlparse(url).path
		contentExtension = os.path.splitext(memrisePath)[1]
		localName = format("%s%s" % (Memrise_Course_Importer.uuid.uuid4(), contentExtension))
		fullMediaPath = os.path.join(mediaDirectoryPath, localName)
		mediaFile = open(fullMediaPath, "wb")
		mediaFile.write(urllib2.urlopen(url).read())
		mediaFile.close()
		return localName
	
	def prepareText(self, content):
		return u'{:s}'.format(content.strip())
	
	def prepareAudio(self, content):
		return u'[sound:{:s}]'.format(self.downloadMedia(content))
	
	def prepareImage(self, content):
		return u'<img src="{:s}">'.format(self.downloadMedia(content))

	def getNoteFromFields(self, fields, tags=[]):
		note = ForeignNote()
		note.fields.extend(fields)
		note.tags.extend(tags)
		return note
	
	def prepareTag(self, tag):
		value = ''.join(x for x in tag.title() if x.isalnum())
		if value.isdigit():
			return ''
		return value
	
	def prepareLevelTag(self, levelNum, width):
		formatstr = u"Level{:0"+str(width)+"d}"
		return formatstr.format(levelNum)

	def getLevelNotes(self, levelNum, tags=[]):
		levelUrl = self.getLevelUrl(levelNum)
		soup = BeautifulSoup(self.downloadWithRetry(levelUrl, 3))
		
		# this looked a lot nicer when I thought I could use BS4 (w/ css selectors)
		# unfortunately Anki is still packaging BS3 so it's a little rougher
		# find the words in column a, whether they be text, image or audio
		colAParents = map(lambda x: x.find("div"), soup.findAll("div", "col_a"))
		colA = map(lambda x: self.prepareText(x.string), filter(lambda p: p["class"] == "text", colAParents))
		colA.extend(map(lambda x: self.prepareImage(x.find("img")["src"]), filter(lambda p: p["class"] == "image", colAParents)))
		colA.extend(map(lambda x: self.prepareAudio(x.find("a")["href"]), filter(lambda p: p["class"] == "audio", colAParents)))
		
		# same deal for column b
		colBParents = map(lambda x: x.find("div"), soup.findAll("div", "col_b"))
		colB = map(lambda x: self.prepareText(x.string), filter(lambda p: p["class"] == "text", colBParents))
		colB.extend(map(lambda x: self.prepareImage(x.find("img")["src"]), filter(lambda p: p["class"] == "image", colBParents)))
		colB.extend(map(lambda x: self.prepareAudio(x.find("a")["href"]), filter(lambda p: p["class"] == "audio", colBParents)))
			
		# pair the "fronts" and "backs" of the notes up
		# this is actually the reverse of what you might expect
		# the content in column A on memrise is typically what you're
		# expected to *produce*, so it goes on the back of the note
		return map(lambda x: self.getNoteFromFields(x, tags), zip(colB, colA))

	def open(self):
		# make sure the url given actually looks like a course home url
		if re.match('http://www.memrise.com/course/\d+/.+/', self.file) == None:
			raise Exception("Import failed. Does your URL look like the sample URL above?")
		return self.file

	def foreignNotes(self):
		self.open()
			
		courseTitle, levelTitles = self.loadCourseInfo()
		levelCount = len(levelTitles)
		
		self.selectDeck(courseTitle)
		self.initMapping()
		
		# This looks ridiculous, sorry. Figure out how many zeroes we need
		# to order the subdecks alphabetically, e.g. if there are 100+ levels
		# we'll need to write "Level 001", "Level 002" etc.
		zeroCount = len(str(levelCount))
		
		# fetch notes data for each level
		memriseNotes = []
		for levelNum, levelTitle in enumerate(levelTitles, start=1):
			tags = [self.prepareLevelTag(levelNum, zeroCount)]
			titleTag = self.prepareTag(levelTitle)
			if titleTag:
				tags.append(titleTag)
			memriseNotes.extend(self.getLevelNotes(levelNum, tags))
		
		return memriseNotes

class MemriseImportWidget(QWidget):
	def __init__(self):
		super(MemriseImportWidget, self).__init__()

		# set up the UI, basically
		self.setWindowTitle("Import Memrise Course")
		self.layout = QVBoxLayout(self)
		
		label = QLabel("Enter the home URL of the Memrise course to import\n(e.g. http://www.memrise.com/course/77958/memrise-intro-french/):")
		self.layout.addWidget(label)
		
		self.courseUrlLineEdit = QLineEdit()
		self.layout.addWidget(self.courseUrlLineEdit)
		
		importModeSelectionLayout = QHBoxLayout()
		self.layout.addLayout(importModeSelectionLayout)
		self.importModeSelection = QComboBox()
		self.importModeSelection.addItem("Update if first field matches existing note")
		self.importModeSelection.addItem("Ignore if first field matches existing note")
		self.importModeSelection.addItem("Import even if first field matches existing note")
		importModeSelectionLayout.addWidget(QLabel("Select import mode"))
		importModeSelectionLayout.addWidget(self.importModeSelection)
		self.importModeSelection.setCurrentIndex(0)
		
		patienceLabel = QLabel("Keep in mind that it can take a substantial amount of time to download \nand import your course. Good things come to those who wait!")
		self.layout.addWidget(patienceLabel)
		self.importCourseButton = QPushButton("Import course")
		self.importCourseButton.clicked.connect(self.importCourse)
		self.layout.addWidget(self.importCourseButton)
		
	# not used - the MediaManager class can provide the media directory path
	def selectMediaDirectory(self):
		fileDialog = QFileDialog()
		filename = fileDialog.getExistingDirectory(self, 'Select media folder')
		self.mediaDirectoryPathLineEdit.setText(filename)
		
	def selectDeck(self, deckTitle):	
		# load or create Basic Note Type
		model = mw.col.models.byName(_("Basic"))
		if model is None:
			model = mw.col.models.byName("Basic")
		if model is None:
			model = addBasicModel(mw.col)
		
		# create deck and set note type
		did = mw.col.decks.id(deckTitle)
		deck = mw.col.decks.get(did)
		deck['mid'] = model['id']
		mw.col.decks.save(deck)
		
		# assign new deck to custom model
		model["did"] = deck["id"]
		mw.col.models.save(model)
		
		# select deck and model
		mw.col.decks.select(did)
		mw.col.models.setCurrent(model)
		
	def importCourse(self):
		courseUrl = self.courseUrlLineEdit.text()

		# import into the collection
		importer = MemriseImporter(mw.col, courseUrl)
		importer.setSelectDeckLambda(self.selectDeck)
		importer.allowHTML = True
		importer.importMode = self.importModeSelection.currentIndex()
		importer.run()
		
		# refresh deck browser so user can see the newly imported deck
		mw.deckBrowser.refresh()
		
		# bye!
		self.hide()
	

def startCourseImporter():
	mw.memriseCourseImporter = MemriseImportWidget()
	mw.memriseCourseImporter.show()

action = QAction("Import Memrise Course...", mw)
mw.connect(action, SIGNAL("triggered()"), startCourseImporter)
mw.form.menuTools.addAction(action)