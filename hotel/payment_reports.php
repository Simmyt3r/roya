<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_hotel_logged_in();

$db = new Database();

// Get hotel ID from session
$hotel_id = $_SESSION['hotel_id'];

// Fetch payment reports for this hotel
$query = "SELECT p.id, p.amount, p.status, p.created_at, b.id as booking_id,
                 b.check_in, b.check_out, b.guests
          FROM payments p
          JOIN bookings b ON p.booking_id = b.id
          WHERE b.hotel_id = :hotel_id
          ORDER BY p.created_at DESC";

$db->query($query);
$db->bind(':hotel_id', $hotel_id);
$payments = $db->resultSet();

// Calculate total earnings
$total_earnings = 0;
foreach ($payments as $payment) {
    if ($payment['status'] == 'completed') {
        $total_earnings += $payment['amount'];
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Reports - <?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1><?php echo SITE_NAME; ?></h1>
            <nav>
                <ul>
                    <li><a href="reservation_dashboard.php">Dashboard</a></li>
                    <li><a href="profile_builder.php">Profile Builder</a></li>
                    <li><a href="payment_reports.php">Payment Reports</a></li>
                    <li><a href="../includes/auth.php?logout=1">Logout</a></li>
                </ul>
            </nav>
        </header>
        
        <h2>Payment Reports</h2>
        
        <div class="stats">
            <div class="stat-card">
                <h3>Total Earnings</h3>
                <p>$<?php echo number_format($total_earnings, 2); ?></p>
            </div>
        </div>
        
        <div class="dashboard">
            <div class="main-content">
                <h3>Payment History</h3>
                
                <?php if (empty($payments)): ?>
                    <p>No payments found.</p>
                <?php else: ?>
                    <table class="reservation-table">
                        <thead>
                            <tr>
                                <th>Payment ID</th>
                                <th>Booking ID</th>
                                <th>Check In</th>
                                <th>Check Out</th>
                                <th>Guests</th>
                                <th>Amount</th>
                                <th>Status</th>
                                <th>Date</th>
                            </tr>
                        </thead>
                        <tbody>
                            <?php foreach ($payments as $payment): ?>
                                <tr>
                                    <td><?php echo htmlspecialchars($payment['id']); ?></td>
                                    <td><?php echo htmlspecialchars($payment['booking_id']); ?></td>
                                    <td><?php echo htmlspecialchars($payment['check_in']); ?></td>
                                    <td><?php echo htmlspecialchars($payment['check_out']); ?></td>
                                    <td><?php echo htmlspecialchars($payment['guests']); ?></td>
                                    <td>$<?php echo htmlspecialchars($payment['amount']); ?></td>
                                    <td><span class="status <?php echo htmlspecialchars($payment['status']); ?>"><?php echo ucfirst(htmlspecialchars($payment['status'])); ?></span></td>
                                    <td><?php echo htmlspecialchars($payment['created_at']); ?></td>
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