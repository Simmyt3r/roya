<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

$db = new Database();

// Get hotel ID from URL parameter
$hotel_id = isset($_GET['id']) ? (int)$_GET['id'] : 0;

if ($hotel_id <= 0) {
    header('Location: search.php');
    exit;
}

// Fetch hotel details
$query = "SELECT h.id, h.name, h.email, h.phone, h.address, h.city, h.country, h.description, h.rating, 
                 hp.photos, hp.pricing, hp.availability, hp.amenities, hp.policies
          FROM hotels h 
          JOIN hotel_profiles hp ON h.id = hp.hotel_id 
          WHERE h.id = :hotel_id AND h.is_verified = 1";

$db->query($query);
$db->bind(':hotel_id', $hotel_id);
$hotel = $db->single();

if (!$hotel) {
    header('Location: search.php');
    exit;
}

// Process booking if form is submitted
if ($_SERVER['REQUEST_METHOD'] == 'POST' && is_logged_in()) {
    $check_in = $_POST['check_in'];
    $check_out = $_POST['check_out'];
    $guests = (int)$_POST['guests'];
    
    // In a real implementation, you would calculate the total amount based on pricing and availability
    // For this MVP, we'll use a placeholder value
    $total_amount = 100 * $guests; // Placeholder calculation
    
    $query = "INSERT INTO bookings (user_id, hotel_id, check_in, check_out, guests, total_amount) 
              VALUES (:user_id, :hotel_id, :check_in, :check_out, :guests, :total_amount)";
    
    $db->query($query);
    $db->bind(':user_id', $_SESSION['user_id']);
    $db->bind(':hotel_id', $hotel_id);
    $db->bind(':check_in', $check_in);
    $db->bind(':check_out', $check_out);
    $db->bind(':guests', $guests);
    $db->bind(':total_amount', $total_amount);
    
    if ($db->execute()) {
        $booking_id = $db->dbh->lastInsertId();
        header("Location: booking.php?id=$booking_id");
        exit;
    } else {
        $error = "Booking failed. Please try again.";
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php echo htmlspecialchars($hotel['name']); ?> - <?php echo SITE_NAME; ?></title>
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
                    <?php if (is_logged_in()): ?>
                        <li><a href="account.php">My Account</a></li>
                        <li><a href="../includes/auth.php?logout=1">Logout</a></li>
                    <?php else: ?>
                        <li><a href="login.php">Login</a></li>
                        <li><a href="register.php">Register</a></li>
                    <?php endif; ?>
                </ul>
            </nav>
        </header>
        
        <?php if (isset($error)): ?>
            <div class="error"><?php echo $error; ?></div>
        <?php endif; ?>
        
        <div class="hotel-profile">
            <h2><?php echo htmlspecialchars($hotel['name']); ?></h2>
            
            <div class="hotel-details">
                <p class="rating">Rating: <?php echo htmlspecialchars($hotel['rating']); ?>/5</p>
                <p class="location"><?php echo htmlspecialchars($hotel['city']); ?>, <?php echo htmlspecialchars($hotel['country']); ?></p>
                <p class="description"><?php echo htmlspecialchars($hotel['description']); ?></p>
            </div>
            
            <?php if (!empty($hotel['photos'])): ?>
                <?php $photos = json_decode($hotel['photos'], true); ?>
                <div class="photo-gallery">
                    <?php foreach ($photos as $photo): ?>
                        <img src="<?php echo htmlspecialchars($photo); ?>" alt="<?php echo htmlspecialchars($hotel['name']); ?> photo">
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>
            
            <?php if (!empty($hotel['amenities'])): ?>
                <div class="amenities">
                    <h3>Amenities</h3>
                    <p><?php echo htmlspecialchars($hotel['amenities']); ?></p>
                </div>
            <?php endif; ?>
            
            <?php if (!empty($hotel['policies'])): ?>
                <div class="policies">
                    <h3>Policies</h3>
                    <p><?php echo htmlspecialchars($hotel['policies']); ?></p>
                </div>
            <?php endif; ?>
            
            <div class="booking-section">
                <h3>Book This Hotel</h3>
                <?php if (is_logged_in()): ?>
                    <form method="POST" action="">
                        <div class="form-row">
                            <div class="form-group">
                                <label for="check_in">Check In</label>
                                <input type="date" id="check_in" name="check_in" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="check_out">Check Out</label>
                                <input type="date" id="check_out" name="check_out" required>
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label for="guests">Number of Guests</label>
                            <select id="guests" name="guests" required>
                                <?php for ($i = 1; $i <= 10; $i++): ?>
                                    <option value="<?php echo $i; ?>"><?php echo $i; ?> <?php echo ($i == 1) ? 'Guest' : 'Guests'; ?></option>
                                <?php endfor; ?>
                            </select>
                        </div>
                        
                        <button type="submit">Proceed to Booking</button>
                    </form>
                <?php else: ?>
                    <p>Please <a href="login.php">login</a> or <a href="register.php">register</a> to book this hotel.</p>
                <?php endif; ?>
            </div>
        </div>
    </div>
</body>
</html>