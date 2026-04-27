<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_hotel_logged_in();

$db = new Database();

// Get hotel ID from session
$hotel_id = $_SESSION['hotel_id'];

// Fetch reservations for this hotel
$query = "SELECT b.id, b.check_in, b.check_out, b.guests, b.total_amount, b.status, b.created_at,
                 u.name as user_name, u.email as user_email
          FROM bookings b
          JOIN users u ON b.user_id = u.id
          WHERE b.hotel_id = :hotel_id
          ORDER BY b.created_at DESC";

$db->query($query);
$db->bind(':hotel_id', $hotel_id);
$reservations = $db->resultSet();

// Handle reservation status update
if ($_SERVER['REQUEST_METHOD'] == 'POST' && isset($_POST['reservation_id'])) {
    $reservation_id = (int)$_POST['reservation_id'];
    $status = $_POST['status'];
    
    // Update reservation status
    $query = "UPDATE bookings SET status = :status WHERE id = :reservation_id AND hotel_id = :hotel_id";
    $db->query($query);
    $db->bind(':status', $status);
    $db->bind(':reservation_id', $reservation_id);
    $db->bind(':hotel_id', $hotel_id);
    
    if ($db->execute()) {
        $success = "Reservation status updated successfully!";
        // Refresh reservations data
        $query = "SELECT b.id, b.check_in, b.check_out, b.guests, b.total_amount, b.status, b.created_at,
                         u.name as user_name, u.email as user_email
                  FROM bookings b
                  JOIN users u ON b.user_id = u.id
                  WHERE b.hotel_id = :hotel_id
                  ORDER BY b.created_at DESC";
        $db->query($query);
        $db->bind(':hotel_id', $hotel_id);
        $reservations = $db->resultSet();
    } else {
        $error = "Failed to update reservation status. Please try again.";
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reservation Dashboard - <?php echo SITE_NAME; ?></title>
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
        
        <h2>Reservation Dashboard</h2>
        
        <?php if (isset($success)): ?>
            <div class="success"><?php echo $success; ?></div>
        <?php endif; ?>
        
        <?php if (isset($error)): ?>
            <div class="error"><?php echo $error; ?></div>
        <?php endif; ?>
        
        <div class="dashboard">
            <div class="main-content">
                <h3>Recent Reservations</h3>
                
                <?php if (empty($reservations)): ?>
                    <p>No reservations found.</p>
                <?php else: ?>
                    <table class="reservation-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>User</th>
                                <th>Check In</th>
                                <th>Check Out</th>
                                <th>Guests</th>
                                <th>Amount</th>
                                <th>Status</th>
                                <th>Date</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            <?php foreach ($reservations as $reservation): ?>
                                <tr>
                                    <td><?php echo htmlspecialchars($reservation['id']); ?></td>
                                    <td><?php echo htmlspecialchars($reservation['user_name']); ?> (<?php echo htmlspecialchars($reservation['user_email']); ?>)</td>
                                    <td><?php echo htmlspecialchars($reservation['check_in']); ?></td>
                                    <td><?php echo htmlspecialchars($reservation['check_out']); ?></td>
                                    <td><?php echo htmlspecialchars($reservation['guests']); ?></td>
                                    <td>$<?php echo htmlspecialchars($reservation['total_amount']); ?></td>
                                    <td><span class="status <?php echo htmlspecialchars($reservation['status']); ?>"><?php echo ucfirst(htmlspecialchars($reservation['status'])); ?></span></td>
                                    <td><?php echo htmlspecialchars($reservation['created_at']); ?></td>
                                    <td>
                                        <?php if ($reservation['status'] == 'pending'): ?>
                                            <form method="POST" action="" style="display: inline;">
                                                <input type="hidden" name="reservation_id" value="<?php echo $reservation['id']; ?>">
                                                <select name="status" onchange="this.form.submit()">
                                                    <option value="pending" <?php echo ($reservation['status'] == 'pending') ? 'selected' : ''; ?>>Pending</option>
                                                    <option value="confirmed" <?php echo ($reservation['status'] == 'confirmed') ? 'selected' : ''; ?>>Confirm</option>
                                                    <option value="cancelled" <?php echo ($reservation['status'] == 'cancelled') ? 'selected' : ''; ?>>Cancel</option>
                                                </select>
                                            </form>
                                        <?php else: ?>
                                            <span>No action available</span>
                                        <?php endif; ?>
                                    </td>
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