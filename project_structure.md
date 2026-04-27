# Hotel Booking Platform - Project Structure

## Technology Stack
- Backend: PHP
- Database: MySQL
- Frontend: HTML, CSS, JavaScript
- Payment Processing: Stripe API
- Authentication: PHP sessions with secure password handling

## Directory Structure
```
hotel_booking_platform/
│
├── assets/
│   ├── css/
│   ├── js/
│   └── images/
│
├── includes/
│   ├── config.php
│   ├── database.php
│   ├── auth.php
│   └── functions.php
│
├── admin/
│   ├── dashboard.php
│   ├── approve_hotels.php
│   ├── manage_commissions.php
│   └── reports.php
│
├── hotel/
│   ├── register.php
│   ├── login.php
│   ├── profile.php
│   ├── profile_builder.php
│   ├── reservation_dashboard.php
│   └── payment_reports.php
│
├── user/
│   ├── search.php
│   ├── hotel_profile.php
│   ├── booking.php
│   ├── checkout.php
│   ├── confirmation.php
│   └── account.php
│
├── database/
│   └── schema.sql
│
└── index.php
```