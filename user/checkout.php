<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_logged_in();

$db = new Database();

// Get booking ID from form submission
$booking_id = isset($_POST['booking_id']) ? (int)$_POST['booking_id'] : 0;

if ($booking_id <= 0) {
    header('Location: search.php');
    exit;
}

// Fetch booking details
$query = "SELECT b.id, b.total_amount, b.status,
                 h.name as hotel_name
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

if ($booking['status'] != 'pending') {
    header('Location: booking.php?id=' . $booking_id);
    exit;
}

// Process payment if form is submitted
if ($_SERVER['REQUEST_METHOD'] == 'POST' && isset($_POST['stripeToken'])) {
    // In a real implementation, you would process the payment with Stripe
    // For this MVP, we'll simulate a successful payment
    
    // Update booking status
    $query = "UPDATE bookings SET status = 'confirmed' WHERE id = :booking_id";
    $db->query($query);
    $db->bind(':booking_id', $booking_id);
    $db->execute();
    
    // Insert payment record
    $query = "INSERT INTO payments (booking_id, amount, stripe_payment_id, status) 
              VALUES (:booking_id, :amount, :stripe_payment_id, :status)";
    $db->query($query);
    $db->bind(':booking_id', $booking_id);
    $db->bind(':amount', $booking['total_amount']);
    $db->bind(':stripe_payment_id', 'stripe_token_' . time());
    $db->bind(':status', 'completed');
    $db->execute();
    
    header('Location: booking.php?id=' . $booking_id);
    exit;
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Checkout - <?php echo SITE_NAME; ?></title>
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
        
        <h2>Checkout</h2>
        
        <div class="checkout-details">
            <h3>Booking for <?php echo htmlspecialchars($booking['hotel_name']); ?></h3>
            <p>Booking ID: #<?php echo htmlspecialchars($booking['id']); ?></p>
            <p>Total Amount: $<?php echo htmlspecialchars($booking['total_amount']); ?></p>
            
            <form action="" method="post" id="payment-form">
                <div class="form-group">
                    <label for="card-element">Credit or debit card</label>
                    <div id="card-element"></div>
                    <div id="card-errors" role="alert"></div>
                </div>
                
                <button type="submit">Pay $<?php echo htmlspecialchars($booking['total_amount']); ?></button>
            </form>
        </div>
    </div>
    
    <script>
        // Stripe integration (simplified for MVP)
        var stripe = Stripe('<?php echo STRIPE_PUBLISHABLE_KEY; ?>');
        var elements = stripe.elements();
        
        var cardElement = elements.create('card');
        cardElement.mount('#card-element');
        
        var form = document.getElementById('payment-form');
        
        form.addEventListener('submit', function(event) {
            event.preventDefault();
            
            stripe.createToken(cardElement).then(function(result) {
                if (result.error) {
                    // Display error to user
                    var errorElement = document.getElementById('card-errors');
                    errorElement.textContent = result.error.message;
                } else {
                    // Add token to form and submit
                    var tokenInput = document.createElement('input');
                    tokenInput.setAttribute('type', 'hidden');
                    tokenInput.setAttribute('name', 'stripeToken');
                    tokenInput.setAttribute('value', result.token.id);
                    form.appendChild(tokenInput);
                    form.submit();
                }
            });
        });
    </script>
</body>
</html>