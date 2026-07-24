
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QUrl
app=QApplication([])
v=QWebEngineView()
v.setUrl(QUrl('https://google.com'))
v.show()
app.exec()
