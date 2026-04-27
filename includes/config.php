<?php
// Database configuration
define('DB_HOST', 'localhost');
define('DB_USER', 'root');
define('DB_PASS', '');
define('DB_NAME', 'hotel_booking');

// Stripe configuration
define('STRIPE_PUBLISHABLE_KEY', 'pk_test_XXXXXXXXXXXXXXXXXXXXXXXX');
define('STRIPE_SECRET_KEY', 'sk_test_XXXXXXXXXXXXXXXXXXXXXXXX');

// Site configuration
define('SITE_URL', 'http://localhost:8000');
define('SITE_NAME', 'Hotel Aggregator & Booking Platform');

// Commission rates
define('DEFAULT_COMMISSION_RATE', 0.15);
define('PREMIUM_COMMISSION_RATE', 0.10);

// Registration fees
define('BASIC_REGISTRATION_FEE', 49.00);
define('PREMIUM_REGISTRATION_FEE', 199.00);
?>