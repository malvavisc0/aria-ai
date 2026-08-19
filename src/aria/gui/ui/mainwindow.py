# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QDateTime,
    QLocale,
    QMetaObject,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTime,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QFontDatabase,
    QGradient,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1200, 870)
        MainWindow.setMinimumSize(QSize(1200, 870))
        MainWindow.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        icon = QIcon(QIcon.fromTheme("emblem-system"))
        MainWindow.setWindowIcon(icon)
        self.actionAbout = QAction(MainWindow)
        self.actionAbout.setObjectName("actionAbout")
        icon1 = QIcon(QIcon.fromTheme("help-about"))
        self.actionAbout.setIcon(icon1)
        self.actionAbout.setMenuRole(QAction.MenuRole.AboutRole)
        self.actionQuit = QAction(MainWindow)
        self.actionQuit.setObjectName("actionQuit")
        icon2 = QIcon(QIcon.fromTheme("application-exit"))
        self.actionQuit.setIcon(icon2)
        self.actionQuit.setMenuRole(QAction.MenuRole.QuitRole)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.verticalLayout_main = QVBoxLayout(self.centralwidget)
        self.verticalLayout_main.setSpacing(16)
        self.verticalLayout_main.setObjectName("verticalLayout_main")
        self.verticalLayout_main.setContentsMargins(24, 24, 24, 24)
        self.horizontalLayout_serviceBar = QHBoxLayout()
        self.horizontalLayout_serviceBar.setSpacing(12)
        self.horizontalLayout_serviceBar.setObjectName("horizontalLayout_serviceBar")
        self.label_ServiceStatus = QLabel(self.centralwidget)
        self.label_ServiceStatus.setObjectName("label_ServiceStatus")

        self.horizontalLayout_serviceBar.addWidget(self.label_ServiceStatus)

        self.label_uptime_lbl = QLabel(self.centralwidget)
        self.label_uptime_lbl.setObjectName("label_uptime_lbl")

        self.horizontalLayout_serviceBar.addWidget(self.label_uptime_lbl)

        self.label_ServiceUptime = QLabel(self.centralwidget)
        self.label_ServiceUptime.setObjectName("label_ServiceUptime")

        self.horizontalLayout_serviceBar.addWidget(self.label_ServiceUptime)

        self.horizontalSpacer_serviceBar = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_serviceBar.addItem(self.horizontalSpacer_serviceBar)

        self.pushButton_ServiceStart = QPushButton(self.centralwidget)
        self.pushButton_ServiceStart.setObjectName("pushButton_ServiceStart")
        self.pushButton_ServiceStart.setEnabled(False)

        self.horizontalLayout_serviceBar.addWidget(self.pushButton_ServiceStart)

        self.pushButton_ServiceStop = QPushButton(self.centralwidget)
        self.pushButton_ServiceStop.setObjectName("pushButton_ServiceStop")
        self.pushButton_ServiceStop.setEnabled(False)

        self.horizontalLayout_serviceBar.addWidget(self.pushButton_ServiceStop)

        self.pushButton_ServiceOpen = QPushButton(self.centralwidget)
        self.pushButton_ServiceOpen.setObjectName("pushButton_ServiceOpen")
        self.pushButton_ServiceOpen.setEnabled(False)

        self.horizontalLayout_serviceBar.addWidget(self.pushButton_ServiceOpen)

        self.verticalLayout_main.addLayout(self.horizontalLayout_serviceBar)

        self.tabWidget = QTabWidget(self.centralwidget)
        self.tabWidget.setObjectName("tabWidget")
        self.tabWidget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_home = QWidget()
        self.tab_home.setObjectName("tab_home")
        self.verticalLayout_home = QVBoxLayout(self.tab_home)
        self.verticalLayout_home.setSpacing(16)
        self.verticalLayout_home.setObjectName("verticalLayout_home")
        self.verticalLayout_home.setContentsMargins(20, 20, 20, 20)
        self.horizontalLayout_home_top = QHBoxLayout()
        self.horizontalLayout_home_top.setObjectName("horizontalLayout_home_top")
        self.groupBox_Service = QGroupBox(self.tab_home)
        self.groupBox_Service.setObjectName("groupBox_Service")
        self.groupBox_Service.setMinimumSize(QSize(320, 0))
        self.formLayout_services = QFormLayout(self.groupBox_Service)
        self.formLayout_services.setObjectName("formLayout_services")
        self.formLayout_services.setHorizontalSpacing(16)
        self.formLayout_services.setVerticalSpacing(10)
        self.formLayout_services.setContentsMargins(20, 16, 20, 16)
        self.label_svc_webui_lbl = QLabel(self.groupBox_Service)
        self.label_svc_webui_lbl.setObjectName("label_svc_webui_lbl")

        self.formLayout_services.setWidget(
            0, QFormLayout.ItemRole.LabelRole, self.label_svc_webui_lbl
        )

        self.label_SvcWebUI = QLabel(self.groupBox_Service)
        self.label_SvcWebUI.setObjectName("label_SvcWebUI")

        self.formLayout_services.setWidget(
            0, QFormLayout.ItemRole.FieldRole, self.label_SvcWebUI
        )

        self.label_svc_vllm_lbl = QLabel(self.groupBox_Service)
        self.label_svc_vllm_lbl.setObjectName("label_svc_vllm_lbl")

        self.formLayout_services.setWidget(
            1, QFormLayout.ItemRole.LabelRole, self.label_svc_vllm_lbl
        )

        self.label_SvcVllm = QLabel(self.groupBox_Service)
        self.label_SvcVllm.setObjectName("label_SvcVllm")

        self.formLayout_services.setWidget(
            1, QFormLayout.ItemRole.FieldRole, self.label_SvcVllm
        )

        self.label_svc_whisper_lbl = QLabel(self.groupBox_Service)
        self.label_svc_whisper_lbl.setObjectName("label_svc_whisper_lbl")

        self.formLayout_services.setWidget(
            2, QFormLayout.ItemRole.LabelRole, self.label_svc_whisper_lbl
        )

        self.label_SvcWhisper = QLabel(self.groupBox_Service)
        self.label_SvcWhisper.setObjectName("label_SvcWhisper")

        self.formLayout_services.setWidget(
            2, QFormLayout.ItemRole.FieldRole, self.label_SvcWhisper
        )

        self.label_svc_kokoro_lbl = QLabel(self.groupBox_Service)
        self.label_svc_kokoro_lbl.setObjectName("label_svc_kokoro_lbl")

        self.formLayout_services.setWidget(
            3, QFormLayout.ItemRole.LabelRole, self.label_svc_kokoro_lbl
        )

        self.label_SvcKokoro = QLabel(self.groupBox_Service)
        self.label_SvcKokoro.setObjectName("label_SvcKokoro")

        self.formLayout_services.setWidget(
            3, QFormLayout.ItemRole.FieldRole, self.label_SvcKokoro
        )

        self.label_svc_lightpanda_lbl = QLabel(self.groupBox_Service)
        self.label_svc_lightpanda_lbl.setObjectName("label_svc_lightpanda_lbl")

        self.formLayout_services.setWidget(
            4, QFormLayout.ItemRole.LabelRole, self.label_svc_lightpanda_lbl
        )

        self.label_SvcLightpanda = QLabel(self.groupBox_Service)
        self.label_SvcLightpanda.setObjectName("label_SvcLightpanda")

        self.formLayout_services.setWidget(
            4, QFormLayout.ItemRole.FieldRole, self.label_SvcLightpanda
        )

        self.label_svc_docling_lbl = QLabel(self.groupBox_Service)
        self.label_svc_docling_lbl.setObjectName("label_svc_docling_lbl")

        self.formLayout_services.setWidget(
            5, QFormLayout.ItemRole.LabelRole, self.label_svc_docling_lbl
        )

        self.label_SvcDocling = QLabel(self.groupBox_Service)
        self.label_SvcDocling.setObjectName("label_SvcDocling")

        self.formLayout_services.setWidget(
            5, QFormLayout.ItemRole.FieldRole, self.label_SvcDocling
        )

        self.horizontalLayout_home_top.addWidget(self.groupBox_Service)

        self.groupBox_AI_Connection = QGroupBox(self.tab_home)
        self.groupBox_AI_Connection.setObjectName("groupBox_AI_Connection")
        self.verticalLayout_ai_connection = QVBoxLayout(self.groupBox_AI_Connection)
        self.verticalLayout_ai_connection.setObjectName("verticalLayout_ai_connection")
        self.verticalLayout_ai_connection.setContentsMargins(20, 16, 20, 16)
        self.frame_RemoteSettings = QFrame(self.groupBox_AI_Connection)
        self.frame_RemoteSettings.setObjectName("frame_RemoteSettings")
        self.formLayout_remote = QFormLayout(self.frame_RemoteSettings)
        self.formLayout_remote.setObjectName("formLayout_remote")
        self.formLayout_remote.setHorizontalSpacing(16)
        self.formLayout_remote.setVerticalSpacing(12)
        self.label_EndpointUrl = QLabel(self.frame_RemoteSettings)
        self.label_EndpointUrl.setObjectName("label_EndpointUrl")

        self.formLayout_remote.setWidget(
            0, QFormLayout.ItemRole.LabelRole, self.label_EndpointUrl
        )

        self.lineEdit_EndpointUrl = QLineEdit(self.frame_RemoteSettings)
        self.lineEdit_EndpointUrl.setObjectName("lineEdit_EndpointUrl")

        self.formLayout_remote.setWidget(
            0, QFormLayout.ItemRole.FieldRole, self.lineEdit_EndpointUrl
        )

        self.label_ApiKey = QLabel(self.frame_RemoteSettings)
        self.label_ApiKey.setObjectName("label_ApiKey")

        self.formLayout_remote.setWidget(
            1, QFormLayout.ItemRole.LabelRole, self.label_ApiKey
        )

        self.lineEdit_ApiKey = QLineEdit(self.frame_RemoteSettings)
        self.lineEdit_ApiKey.setObjectName("lineEdit_ApiKey")
        self.lineEdit_ApiKey.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)

        self.formLayout_remote.setWidget(
            1, QFormLayout.ItemRole.FieldRole, self.lineEdit_ApiKey
        )

        self.label_Model = QLabel(self.frame_RemoteSettings)
        self.label_Model.setObjectName("label_Model")

        self.formLayout_remote.setWidget(
            2, QFormLayout.ItemRole.LabelRole, self.label_Model
        )

        self.lineEdit_Model = QLineEdit(self.frame_RemoteSettings)
        self.lineEdit_Model.setObjectName("lineEdit_Model")

        self.formLayout_remote.setWidget(
            2, QFormLayout.ItemRole.FieldRole, self.lineEdit_Model
        )

        self.label_ContextSize = QLabel(self.frame_RemoteSettings)
        self.label_ContextSize.setObjectName("label_ContextSize")

        self.formLayout_remote.setWidget(
            3, QFormLayout.ItemRole.LabelRole, self.label_ContextSize
        )

        self.lineEdit_ContextSize = QLineEdit(self.frame_RemoteSettings)
        self.lineEdit_ContextSize.setObjectName("lineEdit_ContextSize")

        self.formLayout_remote.setWidget(
            3, QFormLayout.ItemRole.FieldRole, self.lineEdit_ContextSize
        )

        self.verticalLayout_ai_connection.addWidget(self.frame_RemoteSettings)

        self.horizontalLayout_connection_test = QHBoxLayout()
        self.horizontalLayout_connection_test.setObjectName(
            "horizontalLayout_connection_test"
        )
        self.pushButton_TestConnection = QPushButton(self.groupBox_AI_Connection)
        self.pushButton_TestConnection.setObjectName("pushButton_TestConnection")

        self.horizontalLayout_connection_test.addWidget(self.pushButton_TestConnection)

        self.pushButton_SaveSettings = QPushButton(self.groupBox_AI_Connection)
        self.pushButton_SaveSettings.setObjectName("pushButton_SaveSettings")

        self.horizontalLayout_connection_test.addWidget(self.pushButton_SaveSettings)

        self.label_ConnectionStatus = QLabel(self.groupBox_AI_Connection)
        self.label_ConnectionStatus.setObjectName("label_ConnectionStatus")

        self.horizontalLayout_connection_test.addWidget(self.label_ConnectionStatus)

        self.horizontalSpacer_connection_status = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_connection_test.addItem(
            self.horizontalSpacer_connection_status
        )

        self.verticalLayout_ai_connection.addLayout(
            self.horizontalLayout_connection_test
        )

        self.horizontalLayout_home_top.addWidget(self.groupBox_AI_Connection)

        self.verticalLayout_home.addLayout(self.horizontalLayout_home_top)

        self.horizontalLayout_home_bottom = QHBoxLayout()
        self.horizontalLayout_home_bottom.setObjectName("horizontalLayout_home_bottom")
        self.groupBox_CreateUser = QGroupBox(self.tab_home)
        self.groupBox_CreateUser.setObjectName("groupBox_CreateUser")
        self.formLayout_createUser = QFormLayout(self.groupBox_CreateUser)
        self.formLayout_createUser.setObjectName("formLayout_createUser")
        self.formLayout_createUser.setHorizontalSpacing(16)
        self.formLayout_createUser.setVerticalSpacing(12)
        self.formLayout_createUser.setContentsMargins(20, 16, 20, 16)
        self.label_user_name_lbl = QLabel(self.groupBox_CreateUser)
        self.label_user_name_lbl.setObjectName("label_user_name_lbl")

        self.formLayout_createUser.setWidget(
            0, QFormLayout.ItemRole.LabelRole, self.label_user_name_lbl
        )

        self.lineEdit_UserName = QLineEdit(self.groupBox_CreateUser)
        self.lineEdit_UserName.setObjectName("lineEdit_UserName")

        self.formLayout_createUser.setWidget(
            0, QFormLayout.ItemRole.FieldRole, self.lineEdit_UserName
        )

        self.label_user_email_lbl = QLabel(self.groupBox_CreateUser)
        self.label_user_email_lbl.setObjectName("label_user_email_lbl")

        self.formLayout_createUser.setWidget(
            1, QFormLayout.ItemRole.LabelRole, self.label_user_email_lbl
        )

        self.lineEdit_UserEmail = QLineEdit(self.groupBox_CreateUser)
        self.lineEdit_UserEmail.setObjectName("lineEdit_UserEmail")

        self.formLayout_createUser.setWidget(
            1, QFormLayout.ItemRole.FieldRole, self.lineEdit_UserEmail
        )

        self.label_user_password_lbl = QLabel(self.groupBox_CreateUser)
        self.label_user_password_lbl.setObjectName("label_user_password_lbl")

        self.formLayout_createUser.setWidget(
            2, QFormLayout.ItemRole.LabelRole, self.label_user_password_lbl
        )

        self.lineEdit_UserPassword = QLineEdit(self.groupBox_CreateUser)
        self.lineEdit_UserPassword.setObjectName("lineEdit_UserPassword")
        self.lineEdit_UserPassword.setMaxLength(48)
        self.lineEdit_UserPassword.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)

        self.formLayout_createUser.setWidget(
            2, QFormLayout.ItemRole.FieldRole, self.lineEdit_UserPassword
        )

        self.label_user_confirm_password_lbl = QLabel(self.groupBox_CreateUser)
        self.label_user_confirm_password_lbl.setObjectName(
            "label_user_confirm_password_lbl"
        )

        self.formLayout_createUser.setWidget(
            3, QFormLayout.ItemRole.LabelRole, self.label_user_confirm_password_lbl
        )

        self.lineEdit_UserConfirmPassword = QLineEdit(self.groupBox_CreateUser)
        self.lineEdit_UserConfirmPassword.setObjectName("lineEdit_UserConfirmPassword")
        self.lineEdit_UserConfirmPassword.setMaxLength(48)
        self.lineEdit_UserConfirmPassword.setEchoMode(
            QLineEdit.EchoMode.PasswordEchoOnEdit
        )

        self.formLayout_createUser.setWidget(
            3, QFormLayout.ItemRole.FieldRole, self.lineEdit_UserConfirmPassword
        )

        self.label_PasswordStrength = QLabel(self.groupBox_CreateUser)
        self.label_PasswordStrength.setObjectName("label_PasswordStrength")

        self.formLayout_createUser.setWidget(
            4, QFormLayout.ItemRole.FieldRole, self.label_PasswordStrength
        )

        self.horizontalLayout_createBtn = QHBoxLayout()
        self.horizontalLayout_createBtn.setObjectName("horizontalLayout_createBtn")
        self.pushButton_CreateUser = QPushButton(self.groupBox_CreateUser)
        self.pushButton_CreateUser.setObjectName("pushButton_CreateUser")
        self.pushButton_CreateUser.setEnabled(False)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(
            self.pushButton_CreateUser.sizePolicy().hasHeightForWidth()
        )
        self.pushButton_CreateUser.setSizePolicy(sizePolicy)

        self.horizontalLayout_createBtn.addWidget(self.pushButton_CreateUser)

        self.horizontalSpacer_createBtn = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_createBtn.addItem(self.horizontalSpacer_createBtn)

        self.formLayout_createUser.setLayout(
            5, QFormLayout.ItemRole.FieldRole, self.horizontalLayout_createBtn
        )

        self.horizontalLayout_home_bottom.addWidget(self.groupBox_CreateUser)

        self.groupBox_CurrentUsers = QGroupBox(self.tab_home)
        self.groupBox_CurrentUsers.setObjectName("groupBox_CurrentUsers")
        self.verticalLayout_userList = QVBoxLayout(self.groupBox_CurrentUsers)
        self.verticalLayout_userList.setObjectName("verticalLayout_userList")
        self.verticalLayout_userList.setContentsMargins(20, 16, 20, 16)
        self.listWidget_CurrentUsers = QListWidget(self.groupBox_CurrentUsers)
        self.listWidget_CurrentUsers.setObjectName("listWidget_CurrentUsers")

        self.verticalLayout_userList.addWidget(self.listWidget_CurrentUsers)

        self.horizontalLayout_userButtons = QHBoxLayout()
        self.horizontalLayout_userButtons.setObjectName("horizontalLayout_userButtons")
        self.horizontalSpacer_userBtns = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_userButtons.addItem(self.horizontalSpacer_userBtns)

        self.pushButton_EditUser = QPushButton(self.groupBox_CurrentUsers)
        self.pushButton_EditUser.setObjectName("pushButton_EditUser")
        self.pushButton_EditUser.setEnabled(False)

        self.horizontalLayout_userButtons.addWidget(self.pushButton_EditUser)

        self.pushButton_DeleteUser = QPushButton(self.groupBox_CurrentUsers)
        self.pushButton_DeleteUser.setObjectName("pushButton_DeleteUser")
        self.pushButton_DeleteUser.setEnabled(False)

        self.horizontalLayout_userButtons.addWidget(self.pushButton_DeleteUser)

        self.verticalLayout_userList.addLayout(self.horizontalLayout_userButtons)

        self.horizontalLayout_home_bottom.addWidget(self.groupBox_CurrentUsers)

        self.verticalLayout_home.addLayout(self.horizontalLayout_home_bottom)

        self.tabWidget.addTab(self.tab_home, "")
        self.tab_knowledge = QWidget()
        self.tab_knowledge.setObjectName("tab_knowledge")
        self.verticalLayout_knowledge = QVBoxLayout(self.tab_knowledge)
        self.verticalLayout_knowledge.setSpacing(16)
        self.verticalLayout_knowledge.setObjectName("verticalLayout_knowledge")
        self.verticalLayout_knowledge.setContentsMargins(20, 20, 20, 20)
        self.horizontalLayout_kbStatus = QHBoxLayout()
        self.horizontalLayout_kbStatus.setSpacing(12)
        self.horizontalLayout_kbStatus.setObjectName("horizontalLayout_kbStatus")
        self.label_KbStatus = QLabel(self.tab_knowledge)
        self.label_KbStatus.setObjectName("label_KbStatus")

        self.horizontalLayout_kbStatus.addWidget(self.label_KbStatus)

        self.label_KbDigest = QLabel(self.tab_knowledge)
        self.label_KbDigest.setObjectName("label_KbDigest")

        self.horizontalLayout_kbStatus.addWidget(self.label_KbDigest)

        self.label_KbCounts = QLabel(self.tab_knowledge)
        self.label_KbCounts.setObjectName("label_KbCounts")

        self.horizontalLayout_kbStatus.addWidget(self.label_KbCounts)

        self.label_KbLastIndex = QLabel(self.tab_knowledge)
        self.label_KbLastIndex.setObjectName("label_KbLastIndex")

        self.horizontalLayout_kbStatus.addWidget(self.label_KbLastIndex)

        self.horizontalSpacer_kbStatus = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_kbStatus.addItem(self.horizontalSpacer_kbStatus)

        self.verticalLayout_knowledge.addLayout(self.horizontalLayout_kbStatus)

        self.listWidget_KnowledgeFiles = QListWidget(self.tab_knowledge)
        self.listWidget_KnowledgeFiles.setObjectName("listWidget_KnowledgeFiles")

        self.verticalLayout_knowledge.addWidget(self.listWidget_KnowledgeFiles)

        self.horizontalLayout_kbButtons = QHBoxLayout()
        self.horizontalLayout_kbButtons.setObjectName("horizontalLayout_kbButtons")
        self.pushButton_KbAdd = QPushButton(self.tab_knowledge)
        self.pushButton_KbAdd.setObjectName("pushButton_KbAdd")

        self.horizontalLayout_kbButtons.addWidget(self.pushButton_KbAdd)

        self.pushButton_KbRemove = QPushButton(self.tab_knowledge)
        self.pushButton_KbRemove.setObjectName("pushButton_KbRemove")

        self.horizontalLayout_kbButtons.addWidget(self.pushButton_KbRemove)

        self.horizontalSpacer_kbButtons = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_kbButtons.addItem(self.horizontalSpacer_kbButtons)

        self.pushButton_KbReindex = QPushButton(self.tab_knowledge)
        self.pushButton_KbReindex.setObjectName("pushButton_KbReindex")

        self.horizontalLayout_kbButtons.addWidget(self.pushButton_KbReindex)

        self.pushButton_KbForceReindex = QPushButton(self.tab_knowledge)
        self.pushButton_KbForceReindex.setObjectName("pushButton_KbForceReindex")

        self.horizontalLayout_kbButtons.addWidget(self.pushButton_KbForceReindex)

        self.verticalLayout_knowledge.addLayout(self.horizontalLayout_kbButtons)

        self.tabWidget.addTab(self.tab_knowledge, "")
        self.tab_logs = QWidget()
        self.tab_logs.setObjectName("tab_logs")
        self.verticalLayout_logs = QVBoxLayout(self.tab_logs)
        self.verticalLayout_logs.setSpacing(16)
        self.verticalLayout_logs.setObjectName("verticalLayout_logs")
        self.verticalLayout_logs.setContentsMargins(20, 20, 20, 20)
        self.horizontalLayout_logFilter = QHBoxLayout()
        self.horizontalLayout_logFilter.setObjectName("horizontalLayout_logFilter")
        self.lineEdit_LogSearch = QLineEdit(self.tab_logs)
        self.lineEdit_LogSearch.setObjectName("lineEdit_LogSearch")
        self.lineEdit_LogSearch.setClearButtonEnabled(True)

        self.horizontalLayout_logFilter.addWidget(self.lineEdit_LogSearch)

        self.comboBox_LogFilter = QComboBox(self.tab_logs)
        self.comboBox_LogFilter.addItem("")
        self.comboBox_LogFilter.addItem("")
        self.comboBox_LogFilter.addItem("")
        self.comboBox_LogFilter.addItem("")
        self.comboBox_LogFilter.setObjectName("comboBox_LogFilter")
        self.comboBox_LogFilter.setMinimumContentsLength(8)

        self.horizontalLayout_logFilter.addWidget(self.comboBox_LogFilter)

        self.verticalLayout_logs.addLayout(self.horizontalLayout_logFilter)

        self.textEdit_Logs = QTextEdit(self.tab_logs)
        self.textEdit_Logs.setObjectName("textEdit_Logs")
        self.textEdit_Logs.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.textEdit_Logs.setReadOnly(True)

        self.verticalLayout_logs.addWidget(self.textEdit_Logs)

        self.horizontalLayout_logsToolbar = QHBoxLayout()
        self.horizontalLayout_logsToolbar.setObjectName("horizontalLayout_logsToolbar")
        self.pushButton_AutoRefresh = QPushButton(self.tab_logs)
        self.pushButton_AutoRefresh.setObjectName("pushButton_AutoRefresh")

        self.horizontalLayout_logsToolbar.addWidget(self.pushButton_AutoRefresh)

        self.horizontalSpacer_logsToolbar = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_logsToolbar.addItem(self.horizontalSpacer_logsToolbar)

        self.pushButton_RefreshLogs = QPushButton(self.tab_logs)
        self.pushButton_RefreshLogs.setObjectName("pushButton_RefreshLogs")

        self.horizontalLayout_logsToolbar.addWidget(self.pushButton_RefreshLogs)

        self.verticalLayout_logs.addLayout(self.horizontalLayout_logsToolbar)

        self.tabWidget.addTab(self.tab_logs, "")

        self.verticalLayout_main.addWidget(self.tabWidget)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menuBar = QMenuBar(MainWindow)
        self.menuBar.setObjectName("menuBar")
        self.menuBar.setGeometry(QRect(0, 0, 800, 30))
        self.menuApplication = QMenu(self.menuBar)
        self.menuApplication.setObjectName("menuApplication")
        self.menuHelp = QMenu(self.menuBar)
        self.menuHelp.setObjectName("menuHelp")
        MainWindow.setMenuBar(self.menuBar)
        self.statusBar = QStatusBar(MainWindow)
        self.statusBar.setObjectName("statusBar")
        MainWindow.setStatusBar(self.statusBar)

        self.menuBar.addAction(self.menuApplication.menuAction())
        self.menuBar.addAction(self.menuHelp.menuAction())
        self.menuApplication.addAction(self.actionQuit)
        self.menuHelp.addAction(self.actionAbout)

        self.retranslateUi(MainWindow)

        self.tabWidget.setCurrentIndex(0)

        QMetaObject.connectSlotsByName(MainWindow)

    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(
            QCoreApplication.translate("MainWindow", "Aria", None)
        )
        self.actionAbout.setText(
            QCoreApplication.translate("MainWindow", "About", None)
        )
        self.actionQuit.setText(QCoreApplication.translate("MainWindow", "Quit", None))
        # if QT_CONFIG(shortcut)
        self.actionQuit.setShortcut(
            QCoreApplication.translate("MainWindow", "Ctrl+Q", None)
        )
        # endif // QT_CONFIG(shortcut)
        self.label_ServiceStatus.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.label_uptime_lbl.setText(
            QCoreApplication.translate("MainWindow", "Uptime", None)
        )
        self.label_ServiceUptime.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.pushButton_ServiceStart.setText(
            QCoreApplication.translate("MainWindow", "Start Server", None)
        )
        self.pushButton_ServiceStop.setText(
            QCoreApplication.translate("MainWindow", "Stop Server", None)
        )
        self.pushButton_ServiceOpen.setText(
            QCoreApplication.translate("MainWindow", "Open Chat", None)
        )
        self.groupBox_Service.setTitle(
            QCoreApplication.translate("MainWindow", "Services", None)
        )
        self.label_svc_webui_lbl.setText(
            QCoreApplication.translate("MainWindow", "Web UI", None)
        )
        self.label_SvcWebUI.setText(QCoreApplication.translate("MainWindow", "-", None))
        self.label_svc_vllm_lbl.setText(
            QCoreApplication.translate("MainWindow", "vLLM", None)
        )
        self.label_SvcVllm.setText(QCoreApplication.translate("MainWindow", "-", None))
        self.label_svc_whisper_lbl.setText(
            QCoreApplication.translate("MainWindow", "Whisper STT", None)
        )
        self.label_SvcWhisper.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.label_svc_kokoro_lbl.setText(
            QCoreApplication.translate("MainWindow", "Kokoro TTS", None)
        )
        self.label_SvcKokoro.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.label_svc_lightpanda_lbl.setText(
            QCoreApplication.translate("MainWindow", "Lightpanda", None)
        )
        self.label_SvcLightpanda.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.label_svc_docling_lbl.setText(
            QCoreApplication.translate("MainWindow", "Docling", None)
        )
        self.label_SvcDocling.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.groupBox_AI_Connection.setTitle(
            QCoreApplication.translate("MainWindow", "OpenAI API Connection", None)
        )
        self.label_EndpointUrl.setText(
            QCoreApplication.translate("MainWindow", "Endpoint URL", None)
        )
        self.lineEdit_EndpointUrl.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "https://api.openai.com/v1", None)
        )
        self.label_ApiKey.setText(
            QCoreApplication.translate("MainWindow", "API Key", None)
        )
        self.lineEdit_ApiKey.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "sk-...", None)
        )
        self.label_Model.setText(
            QCoreApplication.translate("MainWindow", "Model", None)
        )
        self.lineEdit_Model.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "gpt-4o", None)
        )
        self.label_ContextSize.setText(
            QCoreApplication.translate("MainWindow", "Context Size", None)
        )
        self.lineEdit_ContextSize.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "65536", None)
        )
        self.pushButton_TestConnection.setText(
            QCoreApplication.translate("MainWindow", "Test Connection", None)
        )
        self.pushButton_SaveSettings.setText(
            QCoreApplication.translate("MainWindow", "Save Settings", None)
        )
        self.label_ConnectionStatus.setText("")
        self.groupBox_CreateUser.setTitle(
            QCoreApplication.translate("MainWindow", "New User", None)
        )
        self.label_user_name_lbl.setText(
            QCoreApplication.translate("MainWindow", "Name", None)
        )
        self.lineEdit_UserName.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "Full name", None)
        )
        self.label_user_email_lbl.setText(
            QCoreApplication.translate("MainWindow", "Email", None)
        )
        self.lineEdit_UserEmail.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "user@example.com", None)
        )
        self.label_user_password_lbl.setText(
            QCoreApplication.translate("MainWindow", "Password", None)
        )
        self.lineEdit_UserPassword.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "Min. 6 characters", None)
        )
        self.label_user_confirm_password_lbl.setText(
            QCoreApplication.translate("MainWindow", "Confirm Password", None)
        )
        self.lineEdit_UserConfirmPassword.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "Re-enter password", None)
        )
        self.label_PasswordStrength.setText("")
        self.pushButton_CreateUser.setText(
            QCoreApplication.translate("MainWindow", "Add User", None)
        )
        self.groupBox_CurrentUsers.setTitle(
            QCoreApplication.translate("MainWindow", "Current Users", None)
        )
        self.pushButton_EditUser.setText(
            QCoreApplication.translate("MainWindow", "Edit", None)
        )
        self.pushButton_DeleteUser.setText(
            QCoreApplication.translate("MainWindow", "Remove", None)
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tab_home),
            QCoreApplication.translate("MainWindow", "Home", None),
        )
        self.label_KbStatus.setText(QCoreApplication.translate("MainWindow", "-", None))
        self.label_KbDigest.setText(QCoreApplication.translate("MainWindow", "-", None))
        self.label_KbCounts.setText(QCoreApplication.translate("MainWindow", "-", None))
        self.label_KbLastIndex.setText(
            QCoreApplication.translate("MainWindow", "-", None)
        )
        self.pushButton_KbAdd.setText(
            QCoreApplication.translate("MainWindow", "Add Files\u2026", None)
        )
        self.pushButton_KbRemove.setText(
            QCoreApplication.translate("MainWindow", "Remove Selected", None)
        )
        self.pushButton_KbReindex.setText(
            QCoreApplication.translate("MainWindow", "Reindex", None)
        )
        self.pushButton_KbForceReindex.setText(
            QCoreApplication.translate("MainWindow", "Force Reindex", None)
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tab_knowledge),
            QCoreApplication.translate("MainWindow", "Knowledge", None),
        )
        self.lineEdit_LogSearch.setPlaceholderText(
            QCoreApplication.translate("MainWindow", "Search logs\u2026", None)
        )
        self.comboBox_LogFilter.setItemText(
            0, QCoreApplication.translate("MainWindow", "All", None)
        )
        self.comboBox_LogFilter.setItemText(
            1, QCoreApplication.translate("MainWindow", "ERROR", None)
        )
        self.comboBox_LogFilter.setItemText(
            2, QCoreApplication.translate("MainWindow", "WARNING", None)
        )
        self.comboBox_LogFilter.setItemText(
            3, QCoreApplication.translate("MainWindow", "INFO", None)
        )

        self.pushButton_AutoRefresh.setText(
            QCoreApplication.translate("MainWindow", "Pause", None)
        )
        self.pushButton_RefreshLogs.setText(
            QCoreApplication.translate("MainWindow", "Refresh", None)
        )
        self.tabWidget.setTabText(
            self.tabWidget.indexOf(self.tab_logs),
            QCoreApplication.translate("MainWindow", "Logs", None),
        )
        self.menuApplication.setTitle(
            QCoreApplication.translate("MainWindow", "File", None)
        )
        self.menuHelp.setTitle(QCoreApplication.translate("MainWindow", "Help", None))

    # retranslateUi
