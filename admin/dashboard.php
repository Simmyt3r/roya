<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_admin_logged_in();

$db = new Database();

// Fetch statistics
$hotel_count_query = "SELECT COUNT(*) as count FROM hotels";
$db->query($hotel_count_query);
$hotel_count = $db->single()['count'];

$verified_hotel_count_query = "SELECT COUNT(*) as count FROM hotels WHERE is_verified = 1";
$db->query($verified_hotel_count_query);
$verified_hotel_count = $db->single()['count'];

$user_count_query = "SELECT COUNT(*) as count FROM users";
$db->query($user_count_query);
$user_count = $db->single()['count'];

$booking_count_query = "SELECT COUNT(*) as count FROM bookings";
$db->query($booking_count_query);
$booking_count = $db->single()['count'];

$recent_bookings_query = "SELECT b.id, b.check_in, b.check_out, b.total_amount, b.status,
                                 h.name as hotel_name, u.name as user_name
                          FROM bookings b
                          JOIN hotels h ON b.hotel_id = h.id
                          JOIN users u ON b.user_id = u.id
                          ORDER BY b.created_at DESC LIMIT 10";
$db->query($recent_bookings_query);
$recent_bookings = $db->resultSet();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard - <?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1><?php echo SITE_NAME; ?> - Admin Dashboard</h1>
            <nav>
                <ul>
                    <li><a href="dashboard.php">Dashboard</a></li>
                    <li><a href="approve_hotels.php">Approve Hotels</a></li>
                    <li><a href="manage_commissions.php">Manage Commissions</a></li>
                    <li><a href="reports.php">Reports</a></li>
                    <li><a href="../includes/auth.php?logout=1">Logout</a></li>
                </ul>
            </nav>
        </header>
        
        <h2>Dashboard Overview</h2>
        
        <div class="stats">
            <div class="stat-card">
                <h3>Total Hotels</h3>
                <p><?php echo $hotel_count; ?></p>
            </div>
            
            <div class="stat-card">
                <h3>Verified Hotels</h3>
                <p><?php echo $verified_hotel_count; ?></p>
            </div>
            
            <div class="stat-card">
                <h3>Registered Users</h3>
                <p><?php echo $user_count; ?></p>
            </div>
            
            <div class="stat-card">
                <h3>Total Bookings</h3>
                <p><?php echo $booking_count; ?></p>
            </div>
        </div>
        
        <div class="dashboard">
            <div class="main-content">
                <h3>Recent Bookings</h3>
                
                <?php if (empty($recent_bookings)): ?>
                    <p>No bookings found.</p>
                <?php else: ?>
                    <table class="reservation-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Hotel</th>
                                <th>User</th>
                                <th>Check In</th>
                                <th>Check Out</th>
                                <th>Amount</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            <?php foreach ($recent_bookings as $booking): ?>
                                <tr>
                                    <td><?php echo htmlspecialchars($booking['id']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['hotel_name']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['user_name']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['check_in']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['check_out']); ?></td>
                                    <td>$<?php echo htmlspecialchars($booking['total_amount']); ?></td>
                                    <td><span class="status <?php echo htmlspecialchars($booking['status']); ?>"><?php echo ucfirst(htmlspecialchars($booking['status'])); ?></span></td>
                                </tr>
                            <?php endforeach; ?>
                        </tbody>
                    </table>
                <?php endif; ?>
            </div>
        </div>
    </div>
</body>
</html>