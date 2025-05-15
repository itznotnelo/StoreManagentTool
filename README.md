# Asia Store Management System - Checkpoints

## Version 1.0 (2024-05-15)
### Features
- Basic product management (add, edit, delete)
- Barcode scanning with API integration (UPCitemdb and OpenFoodFacts)
- Product search functionality
- Stock management
- Category management
- Stock history tracking with visualization
- Multi-language support (English, German, Chinese)
- User management system
- Export functionality (Excel, PDF, CSV)
- Backup system
- Modern UI with ttkbootstrap

### Stock History Feature
- Tracks stock changes over time
- Visualizes stock levels in a line graph
- Shows stock history for the last 7 days
- Displays stock levels with annotations
- Interactive graph with zoom and pan capabilities

### Database Structure
- Products table with barcode as primary key
- Categories table with relationships
- Stock history table for tracking changes
- Users table for authentication

### Dependencies
- ttkbootstrap
- SQLAlchemy
- matplotlib
- pandas
- openpyxl
- reportlab
- requests
- pillow
- barcode

### How to Use
1. Run `python asia_store.py`
2. Use barcode scanner or manual entry
3. Double-click products to view stock history
4. Use the export function to backup data
5. Manage users through the user management system 