<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_logged_in();

$db = new Database();

// Get user ID from session
$user_id = $_SESSION['user_id'];

// Fetch user's booking history
$query = "SELECT b.id, b.check_in, b.check_out, b.guests, b.total_amount, b.status, b.created_at,
                 h.name as hotel_name
          FROM bookings b
          JOIN hotels h ON b.hotel_id = h.id
          WHERE b.user_id = :user_id
          ORDER BY b.created_at DESC";

$db->query($query);
$db->bind(':user_id', $user_id);
$bookings = $db->resultSet();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Account - <?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1><?php echo SITE_NAME; ?></h1>
            <nav>
                <ul>
                    <li><a href="../index.php">Home</a></li>
                    <li><a href="search.php">Search</a></li>
                    <li><a href="account.php">My Account</a></li>
                    <li><a href="../includes/auth.php?logout=1">Logout</a></li>
                </ul>
            </nav>
        </header>
        
        <h2>My Account</h2>
        
        <div class="dashboard">
            <div class="main-content">
                <h3>My Bookings</h3>
                
                <?php if (empty($bookings)): ?>
                    <p>You have no bookings yet.</p>
                <?php else: ?>
                    <table class="reservation-table">
                        <thead>
                            <tr>
                                <th>Booking ID</th>
                                <th>Hotel</th>
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
                            <?php foreach ($bookings as $booking): ?>
                                <tr>
                                    <td><?php echo htmlspecialchars($booking['id']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['hotel_name']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['check_in']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['check_out']); ?></td>
                                    <td><?php echo htmlspecialchars($booking['guests']); ?></td>
                                    <td>$<?php echo htmlspecialchars($booking['total_amount']); ?></td>
                                    <td><span class="status <?php echo htmlspecialchars($booking['status']); ?>"><?php echo ucfirst(htmlspecialchars($booking['status'])); ?></span></td>
                                    <td><?php echo htmlspecialchars($booking['created_at']); ?></td>
                                    <td>
                                        <?php if ($booking['status'] == 'confirmed'): ?>
                                            <form method="POST" action="" style="display: inline;">
                                                <input type="hidden" name="booking_id" value="<?php echo $booking['id']; ?>">
                                                <button type="submit" name="action" value="cancel" class="btn" style="background-color: #e74c3c;">Cancel</button>
                                            </form>
                                        <?php endif; ?>
                                        <a href="booking.php?id=<?php echo $booking['id']; ?>" class="btn">View</a>
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