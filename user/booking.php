<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_logged_in();

$db = new Database();

// Get booking ID from URL parameter
$booking_id = isset($_GET['id']) ? (int)$_GET['id'] : 0;

if ($booking_id <= 0) {
    header('Location: search.php');
    exit;
}

// Fetch booking details
$query = "SELECT b.id, b.check_in, b.check_out, b.guests, b.total_amount, b.status,
                 h.name as hotel_name, h.email as hotel_email, h.phone as hotel_phone
          FROM bookings b
          JOIN hotels h ON b.hotel_id = h.id
          WHERE b.id = :booking_id AND b.user_id = :user_id";

$db->query($query);
$db->bind(':booking_id', $booking_id);
$db->bind(':user_id', $_SESSION['user_id']);
$booking = $db->single();

if (!$booking) {
    header('Location: account.php');
    exit;
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Booking Confirmation - <?php echo SITE_NAME; ?></title>
    <link rel="stylesheet" href="../assets/css/style.css">
    <script src="https://js.stripe.com/v3/"></script>
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
        
        <h2>Booking Confirmation</h2>
        
        <div class="booking-details">
            <h3>Booking #<?php echo htmlspecialchars($booking['id']); ?></h3>
            
            <div class="hotel-info">
                <h4>Hotel Information</h4>
                <p>Name: <?php echo htmlspecialchars($booking['hotel_name']); ?></p>
                <p>Email: <?php echo htmlspecialchars($booking['hotel_email']); ?></p>
                <p>Phone: <?php echo htmlspecialchars($booking['hotel_phone']); ?></p>
            </div>
            
            <div class="booking-info">
                <h4>Booking Details</h4>
                <p>Check In: <?php echo htmlspecialchars($booking['check_in']); ?></p>
                <p>Check Out: <?php echo htmlspecialchars($booking['check_out']); ?></p>
                <p>Guests: <?php echo htmlspecialchars($booking['guests']); ?></p>
                <p>Total Amount: $<?php echo htmlspecialchars($booking['total_amount']); ?></p>
                <p>Status: <span class="status <?php echo htmlspecialchars($booking['status']); ?>"><?php echo ucfirst(htmlspecialchars($booking['status'])); ?></span></p>
            </div>
            
            <?php if ($booking['status'] == 'pending'): ?>
                <div class="payment-section">
                    <h4>Payment</h4>
                    <p>Please complete your payment to confirm the booking.</p>
                    
                    <form action="checkout.php" method="POST">
                        <input type="hidden" name="booking_id" value="<?php echo $booking_id; ?>">
                        <button type="submit" id="checkout-button">Proceed to Payment</button>
                    </form>
                </div>
            <?php elseif ($booking['status'] == 'confirmed'): ?>
                <div class="confirmation-section">
                    <h4>Booking Confirmed</h4>
                    <p>Your booking has been confirmed. You'll receive a confirmation email shortly.</p>
                    <p>Booking reference: #<?php echo htmlspecialchars($booking['id']); ?></p>
                </div>
            <?php elseif ($booking['status'] == 'cancelled'): ?>
                <div class="cancellation-section">
                    <h4>Booking Cancelled</h4>
                    <p>This booking has been cancelled.</p>
                </div>
            <?php endif; ?>
        </div>
    </div>
</body>
</html>