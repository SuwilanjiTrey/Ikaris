import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton,QVBoxLayout,QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import QObject, pyqtSlot,QUrl

#bridge class for html to python communication
class Handler(QObject):
	@pyqtSlot()
	def hello_world(self):
		print("hello world from html!!!!🥳️")
		

class MyWindow(QMainWindow):
	def __init__(self):
		super().__init__()
		self.setWindowTitle("QT5 WINDOW")
		self.resize(600,500)
		
		#Main layout
		layout = QVBoxLayout()
		central_widget= QWidget()
		central_widget.setLayout(layout)
		self.setCentralWidget(central_widget)
		
		## QT button
		self.btn = QPushButton("Button: say hello")
		self.btn.clicked.connect(self.print_hello)
		layout.addWidget(self.btn)
		
		## Web View
		self.web_view = QWebEngineView()
		
		##set up the bridge
		self.channel = QWebChannel()
		self.handler = Handler()
		self.channel.registerObject('handler', self.handler)
		self.web_view.page().setWebChannel(self.channel)
		
		
		#### HTML CODE
		html_code = """
		<html>
			<head>
				<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
				<script>
					var handler;
					new QWebChannel(qt.webChannelTransport, function (channel){
						handler = channel.objects.handler;
					});
					
					function callPython(){
						if (handler) handler.hello_world();
					}
				</script>
			</head>
			<body style="font-family: sans-serif; background: #f4f4f4; text-align: center;">
				<h3>Hello suwilanji you have made an embedded html page</h3>
				<button onclick="callPython()" style="padding: 10px;">
					Click me
				</button>
			</body>
		</html>
		"""
		
		### Load the embedded code
		#self.web_view.setHtml(html_code)
		
		## for future use: external files like index.html
		self.web_view.load(QUrl.fromLocalFile(os.path.abspath("web/landing.html")))
		
		## web pages
		#self.web_view.setUrl(QUrl("https://suwilanjitreychellah.vercel.app"))
		
		layout.addWidget(self.web_view)
		
	def print_hello(self):
		print("hello world from Python QT button")
		
if __name__ == "__main__":
	sys.argv.append("--disable-web-security")
	app = QApplication(sys.argv)
	window = MyWindow()
	window.show()
	sys.exit(app.exec_()) 
