<?php
require_once 'includes/config.php';
require_once 'includes/database.php';
require_once 'includes/auth.php';

$db = new Database();

// Fetch some statistics for the homepage
$hotel_count_query = "SELECT COUNT(*) as count FROM hotels WHERE is_verified = 1";
$db->query($hotel_count_query);
$hotel_count = $db->single()['count'];

$booking_count_query = "SELECT COUNT(*) as count FROM bookings";
$db->query($booking_count_query);
$booking_count = $db->single()['count'];
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="assets/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1><?php echo SITE_NAME; ?></h1>
            <nav>
                <ul>
                    <li><a href="index.php">Home</a></li>
                    <li><a href="user/search.php">Search</a></li>
                    <?php if (is_logged_in()): ?>
                        <li><a href="user/account.php">My Account</a></li>
                        <li><a href="includes/auth.php?logout=1">Logout</a></li>
                    <?php else: ?>
                        <li><a href="user/login.php">Login</a></li>
                        <li><a href="user/register.php">Register</a></li>
                    <?php endif; ?>
                    
                    <?php if (is_hotel_logged_in()): ?>
                        <li><a href="hotel/reservation_dashboard.php">Hotel Dashboard</a></li>
                        <li><a href="includes/auth.php?logout=1">Logout</a></li>
                    <?php else: ?>
                        <li><a href="hotel/login.php">Hotel Login</a></li>
                    <?php endif; ?>
                    
                    <?php if (is_admin_logged_in()): ?>
                        <li><a href="admin/dashboard.php">Admin Dashboard</a></li>
                        <li><a href="includes/auth.php?logout=1">Logout</a></li>
                    <?php else: ?>
                        <li><a href="admin/login.php">Admin</a></li>
                    <?php endif; ?>
                </ul>
            </nav>
        </header>
        
        <main>
            <section class="hero">
                <h2>Discover and Book Unique Hotels</h2>
                <p>Find the perfect accommodation for your next trip from our curated collection of hotels.</p>
                <a href="user/search.php" class="btn">Search Hotels</a>
            </section>
            
            <section class="stats">
                <div class="stat-card">
                    <h3>Hotels Available</h3>
                    <p><?php echo $hotel_count; ?></p>
                </div>
                
                <div class="stat-card">
                    <h3>Bookings Completed</h3>
                    <p><?php echo $booking_count; ?></p>
                </div>
            </section>
            
            <section class="features">
                <h2>Why Choose Our Platform?</h2>
                <div class="feature-list">
                    <div class="feature">
                        <h3>Fair Pricing</h3>
                        <p>Lower commissions for hotels compared to other platforms.</p>
                    </div>
                    <div class="feature">
                        <h3>Local Focus</h3>
                        <p>Discover unique local hotels that aren't available elsewhere.</p>
                    </div>
                    <div class="feature">
                        <h3>Easy Booking</h3>
                        <p>Simple and secure booking process with instant confirmation.</p>
                    </div>
                </div>
            </section>
        </main>
        
        <footer>
            <p>&copy; <?php echo date('Y'); ?> <?php echo SITE_NAME; ?>. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>