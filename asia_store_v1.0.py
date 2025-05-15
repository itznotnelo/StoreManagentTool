import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from datetime import datetime, timedelta
import barcode
from barcode.writer import ImageWriter
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import pandas as pd
import os
import requests
import keyboard
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import i18n
import schedule
import time
import threading
import shutil
import json
from PIL import Image, ImageTk
import hashlib
import sqlite3
from matplotlib.figure import Figure

# Datenbank-Setup
Base = declarative_base()
engine = create_engine('sqlite:///asia_store.db')
Session = sessionmaker(bind=engine)

# UPCitemdb Demo API Key (Sie können später Ihren eigenen eintragen)
UPCITEMDB_API_KEY = "DEMO_KEY"
UPCITEMDB_ENDPOINT = "https://api.upcitemdb.com/prod/trial/lookup?upc={barcode}"
OPENFOODFACTS_ENDPOINT = "https://world.openfoodfacts.org/api/v0/product/{barcode}.json"

class Category(Base):
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True)
    description = Column(String(200))
    min_stock = Column(Integer, default=5)  # Minimaler Bestand für Warnung
    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = 'products'
    
    barcode = Column(String(50), primary_key=True)
    name = Column(String(100))
    description = Column(String(200))
    price = Column(Float)
    stock = Column(Integer)
    category_id = Column(Integer, ForeignKey('categories.id'))
    category = relationship("Category", back_populates="products")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    image_path = Column(String)
    stock_history = relationship("StockHistory", back_populates="product", cascade="all, delete-orphan")

class StockHistory(Base):
    __tablename__ = 'stock_history'
    
    id = Column(Integer, primary_key=True)
    product_barcode = Column(String(50), ForeignKey('products.barcode'))
    product = relationship("Product", back_populates="stock_history")
    stock_level = Column(Integer)
    timestamp = Column(DateTime, default=datetime.now)
    change_type = Column(String(20))  # 'manual', 'sale', 'restock', etc.
    notes = Column(String(200))

class User(Base):
    __tablename__ = "users"
    
    username = Column(String, primary_key=True)
    password_hash = Column(String)
    role = Column(String)  # admin, manager, user
    last_login = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"

# Erstelle die Datenbank-Tabellen
Base.metadata.create_all(engine)

# Standard-Kategorien erstellen, falls keine existieren
def create_default_categories():
    session = Session()
    if not session.query(Category).first():
        default_categories = [
            ("Nudeln", "Verschiedene Nudelsorten", 10),
            ("Saucen", "Asiatische Saucen und Gewürze", 5),
            ("Snacks", "Asiatische Snacks und Chips", 8),
            ("Getränke", "Asiatische Getränke", 6),
            ("Tiefkühl", "Tiefkühlprodukte", 4),
            ("Reis", "Verschiedene Reissorten", 7),
            ("Gemüse", "Frisches und konserviertes Gemüse", 5),
            ("Fisch & Fleisch", "Fisch- und Fleischprodukte", 3)
        ]
        for name, desc, min_stock in default_categories:
            category = Category(name=name, description=desc, min_stock=min_stock)
            session.add(category)
        session.commit()
    session.close()

create_default_categories()

class AsiaStoreApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Asia Store Management System")
        self.root.geometry("1200x800")
        
        # Database setup
        self.engine = create_engine("sqlite:///asia_store.db")
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        
        # SQLite database
        self.db = sqlite3.connect("asia_store.db")
        self.cursor = self.db.cursor()
        
        # User session (no login)
        self.current_user = {"username": "open", "role": "admin"}
        self.user_permissions = {
            "admin": ["read", "write", "delete", "export", "backup", "restore", "settings", "users"],
            "manager": ["read", "write", "export", "backup"],
            "user": ["read", "write"]
        }
        
        # Initialize variables
        self.name_var = tk.StringVar()
        self.barcode_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.price_var = tk.StringVar()
        self.stock_var = tk.StringVar()
        self.status_var = tk.StringVar()
        
        # Setup language
        self.setup_language()
        
        # Show main window
        self.show_main_window()
        
    def __del__(self):
        """Cleanup when the application is closed"""
        try:
            if hasattr(self, 'session'):
                self.session.close()
            if hasattr(self, 'offline_db'):
                self.offline_db.close()
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")
    
    def init_db(self):
        """Initialisiert die Datenbank"""
        try:
            Base.metadata.create_all(self.engine)
            self.session.commit()
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                f"Database initialization error: {str(e)}"
            )
    
    def get_all_products(self):
        """Gibt alle Produkte zurück"""
        with self.Session() as session:
            return session.query(Product).all()
            
    def get_product_by_barcode(self, barcode):
        """Gibt ein Produkt anhand des Barcodes zurück"""
        with self.Session() as session:
            return session.query(Product).filter_by(barcode=barcode).first()
            
    def delete_product(self):
        """Löscht ein Produkt"""
        if not self.check_permission("delete"):
            messagebox.showerror("Fehler", "Keine Berechtigung zum Löschen")
            return
            
        selection = self.tree.selection()
        if not selection:
            self.warning_var.set("Bitte Produkt auswählen")
            return
            
        if not messagebox.askyesno("Löschen", "Produkt wirklich löschen?"):
            return
            
        item = self.tree.item(selection[0])
        barcode = item["values"][0]
        
        with self.Session() as session:
            product = self.get_product_by_barcode(barcode)
            if product:
                session.delete(product)
                session.commit()
                self.status_var.set("Produkt gelöscht")
                self.update_product_list()
                self.update_charts()
                
    def update_product_list(self):
        """Updates the product list with current data"""
        try:
            # Clear existing items
            for item in self.product_tree.get_children():
                self.product_tree.delete(item)
                
            # Get products from database
            session = self.Session()
            products = session.query(Product).all()
            
            # Add products to treeview
            for product in products:
                self.product_tree.insert("", "end", values=(
                    product.barcode,
                    product.name,
                    product.description or "",
                    product.category.name if product.category else "",
                    f"{product.price:.2f}",
                    product.stock
                ))
                
            session.close()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                f"Error updating product list: {str(e)}"
            )
            
    def export_data(self):
        """Exportiert die Daten"""
        if not self.check_permission("export"):
            messagebox.showerror("Fehler", "Keine Berechtigung zum Exportieren")
            return
            
        self.show_column_selection(self.export_selected_columns)
        
    def export_selected_columns(self, selected_columns):
        """Exportiert die ausgewählten Spalten"""
        if not selected_columns:
            self.warning_var.set("Bitte mindestens eine Spalte auswählen")
            return
            
        # Dateinamen abfragen
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[
                ("Excel", "*.xlsx"),
                ("PDF", "*.pdf"),
                ("CSV", "*.csv")
            ]
        )
        
        if not file_path:
            return
            
        try:
            # Daten vorbereiten
            data = []
            for product in self.get_all_products():
                row = {}
                if "Barcode" in selected_columns:
                    row["Barcode"] = product.barcode
                if "Produktname" in selected_columns:
                    row["Produktname"] = product.name
                if "Kategorie" in selected_columns:
                    row["Kategorie"] = product.category
                if "Beschreibung" in selected_columns:
                    row["Beschreibung"] = product.description
                if "Preis" in selected_columns:
                    row["Preis"] = product.price
                if "Lagerbestand" in selected_columns:
                    row["Lagerbestand"] = product.stock
                if "Mindestbestand" in selected_columns:
                    row["Mindestbestand"] = product.min_stock
                data.append(row)
                
            # Export basierend auf Dateityp
            if file_path.endswith(".xlsx"):
                self.export_excel(data, file_path)
            elif file_path.endswith(".pdf"):
                self.export_pdf(data, file_path)
            elif file_path.endswith(".csv"):
                self.export_csv(data, file_path)
                
            self.status_var.set("Export erfolgreich")
            
        except Exception as e:
            self.warning_var.set(f"Export-Fehler: {str(e)}")
            
    def export_excel(self, data, file_path):
        """Exportiert die Daten als Excel-Datei"""
        df = pd.DataFrame(data)
        writer = pd.ExcelWriter(file_path, engine="openpyxl")
        df.to_excel(writer, index=False, sheet_name="Produkte")
        
        # Formatierung
        worksheet = writer.sheets["Produkte"]
        for idx, col in enumerate(df.columns):
            max_length = max(
                df[col].astype(str).apply(len).max(),
                len(col)
            )
            worksheet.column_dimensions[chr(65 + idx)].width = max_length + 2
            
        writer.close()
        
    def export_pdf(self, data, file_path):
        """Exportiert die Daten als PDF-Datei"""
        doc = SimpleDocTemplate(
            file_path,
            pagesize=landscape(A4),
            rightMargin=30,
            leftMargin=30,
            topMargin=30,
            bottomMargin=30
        )
        
        # Titel
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=24,
            spaceAfter=30
        )
        title = Paragraph("Produktliste", title_style)
        
        # Tabelle
        table_data = [list(data[0].keys())]  # Header
        for row in data:
            table_data.append(list(row.values()))
            
        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 14),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 12),
            ("GRID", (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        # Dokument zusammenstellen
        elements = [title, table]
        doc.build(elements)
        
    def export_csv(self, data, file_path):
        """Exportiert die Daten als CSV-Datei"""
        df = pd.DataFrame(data)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")

    def setup_language(self):
        """Initialisiert das Übersetzungssystem"""
        self.current_language = "de"  # Default language
        
        # Übersetzungen
        self.translations = {
            "de": {
                "app_title": "Asia Store Management System",
                "product_details": "Produktdetails",
                "name": "Name",
                "category": "Kategorie",
                "price": "Preis",
                "stock": "Bestand",
                "min_stock": "Mindestbestand",
                "save": "Speichern",
                "delete": "Löschen",
                "clear": "Felder leeren",
                "product_list": "Produktliste",
                "charts": "Charts",
                "stock_levels": "Bestandsniveaus",
                "categories": "Kategorien",
                "prices": "Preise",
                "min_stock_levels": "Mindestbestandsniveaus",
                "error": "Fehler",
                "success": "Erfolg",
                "warning": "Warnung",
                "info": "Information",
                "product": "Produkt",
                "quantity": "Menge",
                "price_eur": "Preis (€)",
                "edit": "Bearbeiten",
                "export": "Exportieren",
                "settings": "Einstellungen",
                "help": "Hilfe",
                "shortcuts": "Tastaturkürzel",
                "faq": "FAQ",
                "about": "Über",
                "about_text": "Asia Store Management System\nVersion 1.0\n© 2024",
                "faq_offline": "Wie funktioniert der Offline-Modus?",
                "faq_offline_answer": "Im Offline-Modus werden Änderungen lokal gespeichert und später synchronisiert.",
                "faq_backup": "Wie werden Backups erstellt?",
                "faq_backup_answer": "Backups werden automatisch täglich erstellt und können auch manuell erstellt werden.",
                "faq_export": "Welche Exportformate werden unterstützt?",
                "faq_export_answer": "Excel, PDF und CSV werden unterstützt.",
                "faq_permissions": "Wie funktioniert die Benutzerverwaltung?",
                "faq_permissions_answer": "Administratoren können Benutzer erstellen und Berechtigungen verwalten.",
                "login": "Anmelden",
                "username": "Benutzername",
                "password": "Passwort",
                "exit": "Beenden",
                "file": "Datei",
                "new": "Neu",
                "refresh": "Aktualisieren",
                "tools": "Extras",
                "backup": "Backup",
                "user": "Benutzer",
                "change_password": "Passwort ändern",
                "manage_users": "Benutzer verwalten",
                "logout": "Abmelden",
                "barcode": "Barcode",
                "error_empty_fields": "Bitte alle Felder ausfüllen",
                "error_invalid_credentials": "Ungültige Anmeldedaten",
                "error_no_selection": "Bitte ein Produkt auswählen",
                "error_username_exists": "Benutzername existiert bereits",
                "error_password_mismatch": "Passwörter stimmen nicht überein",
                "error_no_password": "Bitte Passwort eingeben",
                "error_cannot_delete_self": "Sie können Ihren eigenen Account nicht löschen",
                "confirm": "Bestätigung",
                "confirm_delete": "Möchten Sie das ausgewählte Element wirklich löschen?",
                "ok": "OK",
                "cancel": "Abbrechen",
                "status": "Status",
                "view": "Ansicht"
            },
            "en": {
                "app_title": "Asia Store Management System",
                "product_details": "Product Details",
                "name": "Name",
                "category": "Category",
                "price": "Price",
                "stock": "Stock",
                "min_stock": "Minimum Stock",
                "save": "Save",
                "delete": "Delete",
                "clear": "Clear Fields",
                "product_list": "Product List",
                "charts": "Charts",
                "stock_levels": "Stock Levels",
                "categories": "Categories",
                "prices": "Prices",
                "min_stock_levels": "Minimum Stock Levels",
                "error": "Error",
                "success": "Success",
                "warning": "Warning",
                "info": "Information",
                "product": "Product",
                "quantity": "Quantity",
                "price_eur": "Price (€)",
                "edit": "Edit",
                "export": "Export",
                "settings": "Settings",
                "help": "Help",
                "shortcuts": "Keyboard Shortcuts",
                "faq": "FAQ",
                "about": "About",
                "about_text": "Asia Store Management System\nVersion 1.0\n© 2024",
                "faq_offline": "How does offline mode work?",
                "faq_offline_answer": "In offline mode, changes are stored locally and synchronized later.",
                "faq_backup": "How are backups created?",
                "faq_backup_answer": "Backups are created automatically daily and can also be created manually.",
                "faq_export": "Which export formats are supported?",
                "faq_export_answer": "Excel, PDF and CSV are supported.",
                "faq_permissions": "How does user management work?",
                "faq_permissions_answer": "Administrators can create users and manage permissions.",
                "login": "Login",
                "username": "Username",
                "password": "Password",
                "exit": "Exit",
                "file": "File",
                "new": "New",
                "refresh": "Refresh",
                "tools": "Tools",
                "backup": "Backup",
                "user": "User",
                "change_password": "Change Password",
                "manage_users": "Manage Users",
                "logout": "Logout",
                "barcode": "Barcode",
                "error_empty_fields": "Please fill in all fields",
                "error_invalid_credentials": "Invalid credentials",
                "error_no_selection": "Please select an item",
                "error_username_exists": "Username already exists",
                "error_password_mismatch": "Passwords do not match",
                "error_no_password": "Please enter password",
                "error_cannot_delete_self": "You cannot delete your own account",
                "confirm": "Confirmation",
                "confirm_delete": "Do you really want to delete the selected item?",
                "ok": "OK",
                "cancel": "Cancel",
                "status": "Status",
                "view": "View"
            },
            "zh": {
                "app_title": "亚洲商店管理系统",
                "product_details": "产品详情",
                "name": "名称",
                "category": "类别",
                "price": "价格",
                "stock": "库存",
                "min_stock": "最低库存",
                "save": "保存",
                "delete": "删除",
                "clear": "清空字段",
                "product_list": "产品列表",
                "charts": "图表",
                "stock_levels": "库存水平",
                "categories": "类别",
                "prices": "价格",
                "min_stock_levels": "最低库存水平",
                "error": "错误",
                "success": "成功",
                "warning": "警告",
                "info": "信息",
                "product": "产品",
                "quantity": "数量",
                "price_eur": "价格 (€)",
                "edit": "编辑",
                "export": "导出",
                "settings": "设置",
                "help": "帮助",
                "shortcuts": "键盘快捷键",
                "faq": "常见问题",
                "about": "关于",
                "about_text": "亚洲商店管理系统\n版本 1.0\n© 2024",
                "faq_offline": "离线模式如何工作？",
                "faq_offline_answer": "在离线模式下，更改会本地存储并在稍后同步。",
                "faq_backup": "如何创建备份？",
                "faq_backup_answer": "备份每天自动创建，也可以手动创建。",
                "faq_export": "支持哪些导出格式？",
                "faq_export_answer": "支持 Excel、PDF 和 CSV。",
                "faq_permissions": "用户管理如何工作？",
                "faq_permissions_answer": "管理员可以创建用户和管理权限。",
                "login": "登录",
                "username": "用户名",
                "password": "密码",
                "exit": "退出",
                "file": "文件",
                "new": "新建",
                "refresh": "刷新",
                "tools": "工具",
                "backup": "备份",
                "user": "用户",
                "change_password": "修改密码",
                "manage_users": "用户管理",
                "logout": "登出",
                "barcode": "条形码",
                "error_empty_fields": "请填写所有字段",
                "error_invalid_credentials": "无效的凭据",
                "error_no_selection": "请选择一个项目",
                "error_username_exists": "用户名已存在",
                "error_password_mismatch": "密码不匹配",
                "error_no_password": "请输入密码",
                "error_cannot_delete_self": "您不能删除自己的账户",
                "confirm": "确认",
                "confirm_delete": "您确定要删除所选项目吗？",
                "ok": "确定",
                "cancel": "取消",
                "status": "状态",
                "view": "视图"
            }
        }
        
    def change_language(self, language):
        """Ändert die Sprache"""
        if language in self.translations:
            self.current_language = language
            self.update_ui_texts()
        else:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                f"Language {language} not supported"
            )
        
    def update_ui_texts(self):
        """Aktualisiert alle UI-Texte"""
        # Fenstertitel
        self.root.title(self.translations[self.current_language]["app_title"])
        
        # Produktdetails
        self.product_details_label.configure(
            text=self.translations[self.current_language]["product_details"]
        )
        self.name_label.configure(
            text=self.translations[self.current_language]["name"]
        )
        self.category_label.configure(
            text=self.translations[self.current_language]["category"]
        )
        self.price_label.configure(
            text=self.translations[self.current_language]["price"]
        )
        self.stock_label.configure(
            text=self.translations[self.current_language]["stock"]
        )
        self.min_stock_label.configure(
            text=self.translations[self.current_language]["min_stock"]
        )
        
        # Buttons
        self.save_button.configure(
            text=self.translations[self.current_language]["save"]
        )
        self.delete_button.configure(
            text=self.translations[self.current_language]["delete"]
        )
        self.clear_button.configure(
            text=self.translations[self.current_language]["clear"]
        )
        
        # Produktliste
        self.product_list_label.configure(
            text=self.translations[self.current_language]["product_list"]
        )
        
        # Charts
        self.charts_label.configure(
            text=self.translations[self.current_language]["charts"]
        )
        self.stock_levels_label.configure(
            text=self.translations[self.current_language]["stock_levels"]
        )
        self.categories_label.configure(
            text=self.translations[self.current_language]["categories"]
        )
        self.prices_label.configure(
            text=self.translations[self.current_language]["prices"]
        )
        self.min_stock_levels_label.configure(
            text=self.translations[self.current_language]["min_stock_levels"]
        )
        
        # Status
        self.status_label.configure(
            text=self.translations[self.current_language]["status"]
        )

    def setup_offline_mode(self):
        """Richtet den Offline-Modus ein"""
        # Offline-Datenbank
        self.offline_db = sqlite3.connect("offline.db")
        self.offline_cursor = self.offline_db.cursor()
        
        # Tabelle erstellen
        self.offline_cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL,
                min_stock INTEGER NOT NULL
            )
        """)
        
        # Synchronisierungs-Warteschlange
        self.sync_queue = []
        
        # Offline-Status
        self.is_offline = False
        
    def toggle_offline_mode(self):
        """Schaltet den Offline-Modus um"""
        self.is_offline = not self.is_offline
        
        if self.is_offline:
            # Daten in Offline-DB synchronisieren
            self.sync_to_offline()
        else:
            # Daten in Online-DB synchronisieren
            self.sync_to_online()
            
        # UI aktualisieren
        self.update_ui()
        
    def sync_to_offline(self):
        """Synchronisiert Daten in die Offline-DB"""
        try:
            # Produkte laden
            self.cursor.execute("SELECT * FROM products")
            products = self.cursor.fetchall()
            
            # Offline-DB leeren
            self.offline_cursor.execute("DELETE FROM products")
            
            # Produkte einfügen
            for product in products:
                self.offline_cursor.execute("""
                    INSERT INTO products (id, name, category, price, stock, min_stock)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, product)
                
            self.offline_db.commit()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def sync_to_online(self):
        """Synchronisiert Daten in die Online-DB"""
        try:
            # Warteschlange verarbeiten
            self.process_sync_queue()
            
            # Produkte laden
            self.offline_cursor.execute("SELECT * FROM products")
            products = self.offline_cursor.fetchall()
            
            # Online-DB leeren
            self.cursor.execute("DELETE FROM products")
            
            # Produkte einfügen
            for product in products:
                self.cursor.execute("""
                    INSERT INTO products (id, name, category, price, stock, min_stock)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, product)
                
            self.db.commit()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def queue_change(self, action, data):
        """Fügt eine Änderung zur Warteschlange hinzu"""
        self.sync_queue.append({
            "action": action,
            "data": data,
            "timestamp": datetime.now()
        })
        
    def process_sync_queue(self):
        """Verarbeitet die Synchronisierungs-Warteschlange"""
        for change in self.sync_queue:
            try:
                if change["action"] == "insert":
                    self.cursor.execute("""
                        INSERT INTO products (name, category, price, stock, min_stock)
                        VALUES (?, ?, ?, ?, ?)
                    """, change["data"])
                elif change["action"] == "update":
                    self.cursor.execute("""
                        UPDATE products
                        SET name = ?, category = ?, price = ?, stock = ?, min_stock = ?
                        WHERE id = ?
                    """, change["data"])
                elif change["action"] == "delete":
                    self.cursor.execute("DELETE FROM products WHERE id = ?", (change["data"],))
                    
            except Exception as e:
                messagebox.showerror(
                    self.translations[self.current_language]["error"],
                    str(e)
                )
                
        # Warteschlange leeren
        self.sync_queue = []
        
    def save_product(self):
        """Saves a product to the database"""
        try:
            # Get values
            barcode = self.barcode_var.get()
            name = self.name_var.get()
            description = self.desc_var.get()
            category_name = self.category_var.get()
            price = self.price_var.get()
            stock = self.stock_var.get()
            
            # Validate required fields
            if not all([barcode, name, category_name, price, stock]):
                messagebox.showerror(
                    self.translations[self.current_language]["error"],
                    "Please fill in all required fields (Barcode, Name, Category, Price, Stock)"
                )
                return
                
            try:
                price = float(price)
                stock = int(stock)
            except ValueError:
                messagebox.showerror(
                    self.translations[self.current_language]["error"],
                    "Price must be a number and Stock must be an integer"
                )
                return
                
            # Get or create category
            session = self.Session()
            category = session.query(Category).filter_by(name=category_name).first()
            if not category:
                category = Category(name=category_name)
                session.add(category)
                session.commit()
                
            # Check if product exists
            product = session.query(Product).filter_by(barcode=barcode).first()
            old_stock = product.stock if product else 0
            
            if product:
                # Update existing product
                product.name = name
                product.description = description
                product.category = category
                product.price = price
                product.stock = stock
                product.updated_at = datetime.now()
            else:
                # Create new product
                product = Product(
                    barcode=barcode,
                    name=name,
                    description=description,
                    category=category,
                    price=price,
                    stock=stock
                )
                session.add(product)
            
            # Record stock change if there's a difference
            if old_stock != stock:
                stock_history = StockHistory(
                    product=product,
                    stock_level=stock,
                    change_type='manual',
                    notes=f'Stock changed from {old_stock} to {stock}'
                )
                session.add(stock_history)
            
            session.commit()
            session.close()
            
            # Update UI
            self.update_product_list()
            self.clear_fields()
            self.status_var.set("Product saved successfully")
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                f"Error saving product: {str(e)}"
            )
            
    def delete_product(self):
        """Löscht ein Produkt"""
        try:
            # Auswahl prüfen
            selection = self.product_tree.selection()
            if not selection:
                messagebox.showerror(
                    self.translations[self.current_language]["error"],
                    self.translations[self.current_language]["error_no_selection"]
                )
                return
                
            # ID holen
            product_id = self.product_tree.item(selection[0])["values"][0]
            
            if self.is_offline:
                # Aus Offline-DB löschen
                self.offline_cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                self.offline_db.commit()
                
                # Änderung in Warteschlange
                self.queue_change("delete", product_id)
            else:
                # Aus Online-DB löschen
                self.cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                self.db.commit()
                
            # UI aktualisieren
            self.update_product_list()
            self.clear_fields()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def search_product(self):
        """Searches for a product by barcode using the API"""
        barcode = self.barcode_var.get()
        if not barcode:
            return
            
        try:
            # Try UPCitemdb API first
            response = requests.get(
                UPCITEMDB_ENDPOINT.format(barcode=barcode),
                headers={"Authorization": UPCITEMDB_API_KEY}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("items"):
                    item = data["items"][0]
                    self.name_var.set(item.get("title", ""))
                    self.desc_var.set(item.get("description", ""))
                    self.price_var.set(str(item.get("price", "")))
                    self.status_var.set(f"Product found: {item.get('title', '')}")
                    return
                    
            # If UPCitemdb fails, try OpenFoodFacts
            response = requests.get(
                OPENFOODFACTS_ENDPOINT.format(barcode=barcode)
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == 1:
                    product = data.get("product", {})
                    self.name_var.set(product.get("product_name", ""))
                    self.desc_var.set(product.get("generic_name", ""))
                    self.price_var.set("")  # OpenFoodFacts doesn't provide prices
                    self.status_var.set(f"Product found: {product.get('product_name', '')}")
                    return
                    
            # If both APIs fail, check local database
            session = self.Session()
            product = session.query(Product).filter_by(barcode=barcode).first()
            if product:
                self.name_var.set(product.name)
                self.desc_var.set(product.description or "")
                self.category_var.set(product.category.name if product.category else "")
                self.price_var.set(str(product.price))
                self.stock_var.set(str(product.stock))
                self.status_var.set(f"Product found in database: {product.name}")
            else:
                self.status_var.set("Product not found. Please enter product details.")
                self.clear_fields()
                self.barcode_var.set(barcode)  # Keep the barcode
                self.name_entry.focus_set()  # Focus on name field for manual entry
                
            session.close()
            
        except Exception as e:
            self.status_var.set(f"Error searching product: {str(e)}")
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                f"Error searching product: {str(e)}"
            )
    
    def clear_fields(self):
        self.barcode_var.set('')
        self.name_var.set('')
        self.desc_var.set('')
        self.price_var.set('')
        self.stock_var.set('')
        self.category_var.set('')
        self.status_var.set("Felder geleert")

    def check_permission(self, permission):
        """Überprüft die Berechtigung des Benutzers"""
        return permission in self.user_permissions.get(self.current_user.role, [])

    def logout(self):
        """Führt den Logout durch"""
        if messagebox.askyesno("Logout", "Möchten Sie sich wirklich abmelden?"):
            self.current_user = None
            self.root.destroy()
            self.root = tb.Window(themename="darkly")

    def manage_users(self):
        """Öffnet die Benutzerverwaltung"""
        # Berechtigung prüfen
        if not self.current_user or self.current_user["role"] != "admin":
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                self.translations[self.current_language]["permission_error"]
            )
            return
            
        # Benutzerverwaltungs-Fenster
        user_window = tk.Toplevel(self.root)
        user_window.title(self.translations[self.current_language]["user_management_title"])
        user_window.geometry("800x600")
        
        # Hauptframe
        main_frame = ttk.Frame(user_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Benutzerliste
        list_frame = ttk.LabelFrame(
            main_frame,
            text=self.translations[self.current_language]["user_management"],
            padding="10"
        )
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Treeview
        columns = (
            "username",
            "role",
            "last_login",
            "active"
        )
        self.user_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings"
        )
        
        # Spalten
        self.user_tree.heading("username", text=self.translations[self.current_language]["username"])
        self.user_tree.heading("role", text=self.translations[self.current_language]["role"])
        self.user_tree.heading("last_login", text=self.translations[self.current_language]["last_login"])
        self.user_tree.heading("active", text=self.translations[self.current_language]["active"])
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.user_tree.yview
        )
        self.user_tree.configure(yscrollcommand=scrollbar.set)
        
        # Packen
        self.user_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["new_user"],
            command=self.create_user
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["edit_user"],
            command=self.edit_user
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["delete_user"],
            command=self.delete_user
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["change_password"],
            command=self.change_password
        ).pack(side=tk.LEFT, padx=5)
        
        # Benutzerliste aktualisieren
        self.update_user_list()
        
    def update_user_list(self):
        """Aktualisiert die Benutzerliste"""
        try:
            # Liste leeren
            for item in self.user_tree.get_children():
                self.user_tree.delete(item)
                
            # Benutzer laden
            self.cursor.execute("SELECT * FROM users")
            users = self.cursor.fetchall()
            
            # Benutzer anzeigen
            for user in users:
                self.user_tree.insert("", tk.END, values=(
                    user[0],  # username
                    user[2],  # role
                    user[3],  # last_login
                    user[4]   # active
                ))
                
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                self.translations[self.current_language]["error_loading_user"]
            )
            
    def create_user(self):
        """Erstellt einen neuen Benutzer"""
        # Dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translations[self.current_language]["new_user"])
        dialog.geometry("400x300")
        
        # Hauptframe
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Eingabefelder
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["username"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        username_var = tk.StringVar()
        ttk.Entry(
            main_frame,
            textvariable=username_var
        ).pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["password"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        password_var = tk.StringVar()
        ttk.Entry(
            main_frame,
            textvariable=password_var,
            show="*"
        ).pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["confirm_password"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        confirm_var = tk.StringVar()
        ttk.Entry(
            main_frame,
            textvariable=confirm_var,
            show="*"
        ).pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["role"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        role_var = tk.StringVar(value="user")
        ttk.Combobox(
            main_frame,
            textvariable=role_var,
            values=[
                self.translations[self.current_language]["admin"],
                self.translations[self.current_language]["manager"],
                self.translations[self.current_language]["user"]
            ],
            state="readonly"
        ).pack(fill=tk.X, pady=(0, 10))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["ok"],
            command=lambda: self.save_user(
                dialog,
                username_var.get(),
                password_var.get(),
                confirm_var.get(),
                role_var.get()
            )
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["cancel"],
            command=dialog.destroy
        ).pack(side=tk.LEFT, padx=5)
        
    def save_user(self, dialog, username, password, confirm, role):
        """Speichert einen Benutzer"""
        try:
            # Validierung
            if not username or not password:
                raise ValueError(
                    self.translations[self.current_language]["error_empty_fields"]
                )
                
            if password != confirm:
                raise ValueError(
                    self.translations[self.current_language]["error_password_mismatch"]
                )
                
            # Benutzername prüfen
            self.cursor.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            )
            if self.cursor.fetchone():
                raise ValueError(
                    self.translations[self.current_language]["error_username_exists"]
                )
                
            # Passwort hashen
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            # Benutzer speichern
            self.cursor.execute("""
                INSERT INTO users (
                    username, password_hash, role, last_login, active
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                username,
                password_hash,
                role,
                datetime.now(),
                True
            ))
            
            # Änderungen speichern
            self.db.commit()
            
            # Dialog schließen
            dialog.destroy()
            
            # Liste aktualisieren
            self.update_user_list()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def edit_user(self):
        """Bearbeitet einen Benutzer"""
        # Auswahl prüfen
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning(
                self.translations[self.current_language]["warning"],
                self.translations[self.current_language]["error_no_selection"]
            )
            return
            
        # Benutzerdaten laden
        item = self.user_tree.item(selected[0])
        username = item["values"][0]
        
        self.cursor.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        )
        user = self.cursor.fetchone()
        
        if not user:
            return
            
        # Dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translations[self.current_language]["edit_user"])
        dialog.geometry("400x200")
        
        # Hauptframe
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Eingabefelder
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["username"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        username_var = tk.StringVar(value=user[0])
        ttk.Entry(
            main_frame,
            textvariable=username_var,
            state="readonly"
        ).pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["role"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        role_var = tk.StringVar(value=user[2])
        ttk.Combobox(
            main_frame,
            textvariable=role_var,
            values=[
                self.translations[self.current_language]["admin"],
                self.translations[self.current_language]["manager"],
                self.translations[self.current_language]["user"]
            ],
            state="readonly"
        ).pack(fill=tk.X, pady=(0, 10))
        
        active_var = tk.BooleanVar(value=user[4])
        ttk.Checkbutton(
            main_frame,
            text=self.translations[self.current_language]["active"],
            variable=active_var
        ).pack(fill=tk.X, pady=(0, 10))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["ok"],
            command=lambda: self.update_user(
                dialog,
                username,
                role_var.get(),
                active_var.get()
            )
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["cancel"],
            command=dialog.destroy
        ).pack(side=tk.LEFT, padx=5)
        
    def update_user(self, dialog, username, role, active):
        """Aktualisiert einen Benutzer"""
        try:
            # Benutzer aktualisieren
            self.cursor.execute("""
                UPDATE users
                SET role = ?, active = ?
                WHERE username = ?
            """, (role, active, username))
            
            # Änderungen speichern
            self.db.commit()
            
            # Dialog schließen
            dialog.destroy()
            
            # Liste aktualisieren
            self.update_user_list()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def delete_user(self):
        """Löscht einen Benutzer"""
        # Auswahl prüfen
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning(
                self.translations[self.current_language]["warning"],
                self.translations[self.current_language]["error_no_selection"]
            )
            return
            
        # Benutzerdaten laden
        item = self.user_tree.item(selected[0])
        username = item["values"][0]
        
        # Eigenen Account prüfen
        if username == self.current_user:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                self.translations[self.current_language]["error_cannot_delete_self"]
            )
            return
            
        # Bestätigung
        if not messagebox.askyesno(
            self.translations[self.current_language]["confirm"],
            self.translations[self.current_language]["confirm_delete"]
        ):
            return
            
        try:
            # Benutzer löschen
            self.cursor.execute(
                "DELETE FROM users WHERE username = ?",
                (username,)
            )
            
            # Änderungen speichern
            self.db.commit()
            
            # Liste aktualisieren
            self.update_user_list()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def change_password(self):
        """Ändert das Passwort eines Benutzers"""
        # Auswahl prüfen
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning(
                self.translations[self.current_language]["warning"],
                self.translations[self.current_language]["error_no_selection"]
            )
            return
            
        # Benutzerdaten laden
        item = self.user_tree.item(selected[0])
        username = item["values"][0]
        
        # Dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(self.translations[self.current_language]["change_password"])
        dialog.geometry("400x200")
        
        # Hauptframe
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Eingabefelder
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["password"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        password_var = tk.StringVar()
        ttk.Entry(
            main_frame,
            textvariable=password_var,
            show="*"
        ).pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            main_frame,
            text=self.translations[self.current_language]["confirm_password"]
        ).pack(fill=tk.X, pady=(0, 5))
        
        confirm_var = tk.StringVar()
        ttk.Entry(
            main_frame,
            textvariable=confirm_var,
            show="*"
        ).pack(fill=tk.X, pady=(0, 10))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["ok"],
            command=lambda: self.update_password(
                dialog,
                username,
                password_var.get(),
                confirm_var.get()
            )
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["cancel"],
            command=dialog.destroy
        ).pack(side=tk.LEFT, padx=5)
        
    def update_password(self, dialog, username, password, confirm):
        """Ändert das Passwort eines Benutzers"""
        try:
            # Validierung
            if not password:
                raise ValueError(
                    self.translations[self.current_language]["error_no_password"]
                )
                
            if password != confirm:
                raise ValueError(
                    self.translations[self.current_language]["error_password_mismatch"]
                )
                
            # Passwort hashen
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            # Benutzer aktualisieren
            self.cursor.execute("""
                UPDATE users
                SET password_hash = ?
                WHERE username = ?
            """, (password_hash, username))
            
            # Änderungen speichern
            self.db.commit()
            
            # Dialog schließen
            dialog.destroy()
            
            # Liste aktualisieren
            self.update_user_list()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                str(e)
            )
            
    def setup_backup(self):
        """Initialisiert das Backup-System"""
        # Standardeinstellungen
        self.backup_settings = {
            "auto_backup": True,
            "backup_time": "23:00",
            "backup_dir": "backups"
        }
        
        # Einstellungen laden
        try:
            if os.path.exists("settings.json"):
                with open("settings.json", "r") as f:
                    self.backup_settings.update(json.load(f))
                    
        except Exception as e:
            print(f"Fehler beim Laden der Einstellungen: {str(e)}")
            
        # Backup-Verzeichnis erstellen
        backup_dir = self.backup_settings.get("backup_dir", "backups")
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        # Automatisches Backup starten
        if self.backup_settings.get("auto_backup", True):
            self.start_auto_backup()
            
    def start_auto_backup(self):
        """Startet das automatische Backup"""
        def backup_job():
            while True:
                try:
                    # Backup-Zeit prüfen
                    now = datetime.now()
                    backup_time = datetime.strptime(
                        self.backup_settings.get("backup_time", "23:00"),
                        "%H:%M"
                    ).time()
                    
                    if now.time() >= backup_time:
                        # Backup erstellen
                        backup_dir = self.backup_settings.get("backup_dir", "backups")
                        if not os.path.exists(backup_dir):
                            os.makedirs(backup_dir)
                            
                        timestamp = now.strftime("%Y%m%d_%H%M%S")
                        backup_file = os.path.join(backup_dir, f"backup_{timestamp}.db")
                        
                        shutil.copy2("asia_store.db", backup_file)
                        print(f"Automatisches Backup erstellt: {backup_file}")
                        
                    # Eine Stunde warten
                    time.sleep(3600)
                    
                except Exception as e:
                    print(f"Fehler beim automatischen Backup: {str(e)}")
                    time.sleep(3600)
                    
        # Backup-Thread starten
        backup_thread = threading.Thread(target=backup_job, daemon=True)
        backup_thread.start()

    def create_charts(self, parent=None):
        """Erstellt die Charts"""
        if parent is None:
            parent = self.charts_tab
        
        # Bestandsniveaus
        self.stock_frame = ttk.LabelFrame(
            parent,
            text=self.translations[self.current_language]["stock_levels"]
        )
        self.stock_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.stock_figure = Figure(figsize=(6, 4), dpi=100)
        self.stock_plot = self.stock_figure.add_subplot(111)
        self.stock_canvas = FigureCanvasTkAgg(self.stock_figure, self.stock_frame)
        self.stock_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Kategorien
        self.category_frame = ttk.LabelFrame(
            parent,
            text=self.translations[self.current_language]["categories"]
        )
        self.category_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.category_figure = Figure(figsize=(6, 4), dpi=100)
        self.category_plot = self.category_figure.add_subplot(111)
        self.category_canvas = FigureCanvasTkAgg(self.category_figure, self.category_frame)
        self.category_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Preise
        self.price_frame = ttk.LabelFrame(
            parent,
            text=self.translations[self.current_language]["prices"]
        )
        self.price_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.price_figure = Figure(figsize=(6, 4), dpi=100)
        self.price_plot = self.price_figure.add_subplot(111)
        self.price_canvas = FigureCanvasTkAgg(self.price_figure, self.price_frame)
        self.price_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Mindestbestandsniveaus
        self.min_stock_frame = ttk.LabelFrame(
            parent,
            text=self.translations[self.current_language]["min_stock_levels"]
        )
        self.min_stock_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.min_stock_figure = Figure(figsize=(6, 4), dpi=100)
        self.min_stock_plot = self.min_stock_figure.add_subplot(111)
        self.min_stock_canvas = FigureCanvasTkAgg(self.min_stock_figure, self.min_stock_frame)
        self.min_stock_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Initial update
        self.update_charts()

    def update_charts(self):
        """Updates the charts with current data"""
        try:
            # Get data from database
            products = self.session.query(Product).all()
            
            if not products:
                return
            
            # Prepare data
            names = [p.name for p in products]
            categories = [p.category.name if p.category else "Uncategorized" for p in products]
            prices = [p.price for p in products]
            stocks = [p.stock for p in products]
            
            # Stock levels
            self.stock_plot.clear()
            self.stock_plot.bar(names, stocks)
            self.stock_plot.set_title(self.translations[self.current_language]["stock_levels"])
            self.stock_plot.set_xlabel(self.translations[self.current_language]["product"])
            self.stock_plot.set_ylabel(self.translations[self.current_language]["quantity"])
            self.stock_plot.tick_params(axis="x", rotation=45)
            self.stock_figure.tight_layout()
            self.stock_canvas.draw()
            
            # Categories
            self.category_plot.clear()
            category_counts = {}
            for category in categories:
                category_counts[category] = category_counts.get(category, 0) + 1
            self.category_plot.pie(
                category_counts.values(),
                labels=category_counts.keys(),
                autopct="%1.1f%%"
            )
            self.category_plot.set_title(self.translations[self.current_language]["categories"])
            self.category_figure.tight_layout()
            self.category_canvas.draw()
            
            # Prices
            self.price_plot.clear()
            self.price_plot.bar(names, prices)
            self.price_plot.set_title(self.translations[self.current_language]["prices"])
            self.price_plot.set_xlabel(self.translations[self.current_language]["product"])
            self.price_plot.set_ylabel(self.translations[self.current_language]["price_eur"])
            self.price_plot.tick_params(axis="x", rotation=45)
            self.price_figure.tight_layout()
            self.price_canvas.draw()
            
        except Exception as e:
            messagebox.showerror(
                self.translations[self.current_language]["error"],
                f"Error updating charts: {str(e)}"
            )

    def show_main_window(self):
        """Shows the main window with a modern, simplified interface"""
        # Configure window
        self.root.title(self.translations[self.current_language]["app_title"])
        self.root.geometry("1200x800")
        
        # Create main container with padding
        main_container = ttk.Frame(self.root, padding="20")
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Create two-column layout
        left_frame = ttk.Frame(main_container)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        right_frame = ttk.Frame(main_container)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # Create product details section
        self.create_product_details(left_frame)
        
        # Create product list section
        self.create_product_list(right_frame)
        
        # Create status bar
        self.create_status_bar()
        
        # Initial update
        self.update_product_list()
        
    def create_product_details(self, parent):
        """Creates a modern product details section focused on barcode scanning"""
        # Main frame with modern styling
        details_frame = ttk.LabelFrame(
            parent,
            text=self.translations[self.current_language]["product_details"],
            padding="20"
        )
        details_frame.pack(fill=tk.BOTH, expand=True)
        
        # Barcode section with large input
        barcode_frame = ttk.Frame(details_frame)
        barcode_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(
            barcode_frame,
            text=self.translations[self.current_language]["barcode"],
            font=("Helvetica", 12, "bold")
        ).pack(anchor=tk.W)
        
        self.barcode_var = tk.StringVar()
        barcode_entry = ttk.Entry(
            barcode_frame,
            textvariable=self.barcode_var,
            font=("Helvetica", 14),
            width=30
        )
        barcode_entry.pack(fill=tk.X, pady=(5, 0))
        barcode_entry.bind('<Return>', lambda e: self.search_product())
        
        # Product info section
        info_frame = ttk.Frame(details_frame)
        info_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Name
        ttk.Label(
            info_frame,
            text=self.translations[self.current_language]["name"],
            font=("Helvetica", 10)
        ).pack(anchor=tk.W)
        
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(
            info_frame,
            textvariable=self.name_var,
            font=("Helvetica", 12)
        )
        name_entry.pack(fill=tk.X, pady=(5, 10))
        
        # Description
        ttk.Label(
            info_frame,
            text="Description",
            font=("Helvetica", 10)
        ).pack(anchor=tk.W)
        
        self.desc_var = tk.StringVar()
        desc_entry = ttk.Entry(
            info_frame,
            textvariable=self.desc_var,
            font=("Helvetica", 12)
        )
        desc_entry.pack(fill=tk.X, pady=(5, 10))
        
        # Category
        ttk.Label(
            info_frame,
            text=self.translations[self.current_language]["category"],
            font=("Helvetica", 10)
        ).pack(anchor=tk.W)
        
        self.category_var = tk.StringVar()
        category_combo = ttk.Combobox(
            info_frame,
            textvariable=self.category_var,
            values=self.get_categories(),
            font=("Helvetica", 12),
            state="readonly"
        )
        category_combo.pack(fill=tk.X, pady=(5, 10))
        
        # Price
        ttk.Label(
            info_frame,
            text=self.translations[self.current_language]["price"],
            font=("Helvetica", 10)
        ).pack(anchor=tk.W)
        
        self.price_var = tk.StringVar()
        price_entry = ttk.Entry(
            info_frame,
            textvariable=self.price_var,
            font=("Helvetica", 12)
        )
        price_entry.pack(fill=tk.X, pady=(5, 10))
        
        # Stock
        ttk.Label(
            info_frame,
            text=self.translations[self.current_language]["stock"],
            font=("Helvetica", 10)
        ).pack(anchor=tk.W)
        
        self.stock_var = tk.StringVar()
        stock_entry = ttk.Entry(
            info_frame,
            textvariable=self.stock_var,
            font=("Helvetica", 12)
        )
        stock_entry.pack(fill=tk.X, pady=(5, 10))
        
        # Buttons with modern styling
        button_frame = ttk.Frame(details_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        save_btn = ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["save"],
            command=self.save_product,
            style="primary.TButton",
            width=20
        )
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        clear_btn = ttk.Button(
            button_frame,
            text=self.translations[self.current_language]["clear"],
            command=self.clear_fields,
            style="secondary.TButton",
            width=20
        )
        clear_btn.pack(side=tk.LEFT)
        
        # Set focus to barcode entry
        barcode_entry.focus_set()
        
    def create_product_list(self, parent):
        """Creates a modern product list section"""
        # Frame with modern styling
        list_frame = ttk.LabelFrame(
            parent,
            text=self.translations[self.current_language]["product_list"],
            padding="20"
        )
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # Treeview with modern styling
        columns = ("barcode", "name", "description", "category", "price", "stock")
        self.product_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            style="modern.Treeview"
        )
        
        # Configure columns
        self.product_tree.heading("barcode", text="Barcode")
        self.product_tree.heading("name", text="Name")
        self.product_tree.heading("description", text="Description")
        self.product_tree.heading("category", text="Category")
        self.product_tree.heading("price", text="Price")
        self.product_tree.heading("stock", text="Stock")
        
        self.product_tree.column("barcode", width=100)
        self.product_tree.column("name", width=150)
        self.product_tree.column("description", width=200)
        self.product_tree.column("category", width=100)
        self.product_tree.column("price", width=80)
        self.product_tree.column("stock", width=80)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.product_tree.yview
        )
        self.product_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack elements
        self.product_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind double-click event
        self.product_tree.bind('<Double-1>', self.on_product_select)
        
    def on_product_select(self, event):
        """Handles product selection from the list"""
        selection = self.product_tree.selection()
        if selection:
            item = self.product_tree.item(selection[0])
            values = item['values']
            self.barcode_var.set(values[0])
            self.name_var.set(values[1])
            self.desc_var.set(values[2])
            self.category_var.set(values[3])
            self.price_var.set(values[4])
            self.stock_var.set(values[5])
            
            # Show stock history diagram
            self.show_stock_history(values[0])

    def create_status_bar(self):
        """Creates a status bar at the bottom of the main window."""
        self.status_var = tk.StringVar(value=self.translations[self.current_language]["status"])
        self.status_label = ttk.Label(self.root, textvariable=self.status_var, anchor="w")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def get_categories(self):
        """Returns a list of category names from the database"""
        try:
            session = self.Session()
            categories = session.query(Category).all()
            session.close()
            return [cat.name for cat in categories]
        except Exception:
            return []

    def show_stock_history(self, barcode):
        """Shows a diagram of stock history for the selected product"""
        try:
            # Create a new window for the diagram
            history_window = tk.Toplevel(self.root)
            history_window.title("Stock History")
            history_window.geometry("800x600")
            
            # Get stock history from database
            session = self.Session()
            product = session.query(Product).filter_by(barcode=barcode).first()
            
            if not product:
                messagebox.showerror("Error", "Product not found")
                return
            
            # Get history for the last week
            one_week_ago = datetime.now() - timedelta(days=7)
            history = session.query(StockHistory).filter(
                StockHistory.product_barcode == barcode,
                StockHistory.timestamp >= one_week_ago
            ).order_by(StockHistory.timestamp).all()
            
            if not history:
                messagebox.showinfo("Info", "No stock history available for the last week")
                return
            
            # Create figure for the diagram
            fig = Figure(figsize=(10, 6))
            ax = fig.add_subplot(111)
            
            # Prepare data
            timestamps = [h.timestamp for h in history]
            stock_levels = [h.stock_level for h in history]
            
            # Plot data
            ax.plot(timestamps, stock_levels, marker='o', linestyle='-', linewidth=2)
            
            # Customize the diagram
            ax.set_title(f"Stock History for {product.name}")
            ax.set_xlabel("Date")
            ax.set_ylabel("Stock Level")
            ax.grid(True)
            
            # Rotate x-axis labels for better readability
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            
            # Add annotations for each point
            for i, (timestamp, level) in enumerate(zip(timestamps, stock_levels)):
                ax.annotate(f'{level}',
                           (timestamp, level),
                           xytext=(10, 10),
                           textcoords='offset points')
            
            # Adjust layout
            fig.tight_layout()
            
            # Create canvas
            canvas = FigureCanvasTkAgg(fig, master=history_window)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            
            # Add toolbar
            toolbar_frame = ttk.Frame(history_window)
            toolbar_frame.pack(fill=tk.X)
            
            # Add close button
            ttk.Button(
                toolbar_frame,
                text="Close",
                command=history_window.destroy
            ).pack(side=tk.RIGHT, padx=5, pady=5)
            
            session.close()
            
        except Exception as e:
            messagebox.showerror("Error", f"Error showing stock history: {str(e)}")
            if 'session' in locals():
                session.close()

if __name__ == "__main__":
    root = tb.Window(themename="flatly")
    app = AsiaStoreApp(root)
    root.mainloop() 