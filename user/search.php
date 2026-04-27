<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

$db = new Database();

// Get search parameters
$location = isset($_GET['location']) ? $_GET['location'] : '';
$check_in = isset($_GET['check_in']) ? $_GET['check_in'] : '';
$check_out = isset($_GET['check_out']) ? $_GET['check_out'] : '';
$guests = isset($_GET['guests']) ? (int)$_GET['guests'] : 1;
$min_price = isset($_GET['min_price']) ? (float)$_GET['min_price'] : 0;
$max_price = isset($_GET['max_price']) ? (float)$_GET['max_price'] : 0;

// Build query based on search parameters
$query = "SELECT h.id, h.name, h.city, h.country, h.description, h.rating, hp.pricing 
          FROM hotels h 
          JOIN hotel_profiles hp ON h.id = hp.hotel_id 
          WHERE h.is_verified = 1";

$params = [];

if (!empty($location)) {
    $query .= " AND (h.city LIKE :location OR h.country LIKE :location)";
    $params[':location'] = "%$location%";
}

if ($min_price > 0) {
    $query .= " AND JSON_EXTRACT(hp.pricing, '$.min_price') >= :min_price";
    $params[':min_price'] = $min_price;
}

if ($max_price > 0) {
    $query .= " AND JSON_EXTRACT(hp.pricing, '$.max_price') <= :max_price";
    $params[':max_price'] = $max_price;
}

$query .= " ORDER BY h.rating DESC";

$db->query($query);
foreach ($params as $key => $value) {
    $db->bind($key, $value);
}
$hotels = $db->resultSet();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search Hotels - <?php echo SITE_NAME; ?></title>
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
        
        <h2>Search Hotels</h2>
        
        <form method="GET" action="" class="search-form">
            <div class="form-group">
                <label for="location">Location</label>
                <input type="text" id="location" name="location" value="<?php echo htmlspecialchars($location); ?>" placeholder="City or country">
            </div>
            
            <div class="form-row">
                <div class="form-group">
                    <label for="check_in">Check In</label>
                    <input type="date" id="check_in" name="check_in" value="<?php echo htmlspecialchars($check_in); ?>">
                </div>
                
                <div class="form-group">
                    <label for="check_out">Check Out</label>
                    <input type="date" id="check_out" name="check_out" value="<?php echo htmlspecialchars($check_out); ?>">
                </div>
                
                <div class="form-group">
                    <label for="guests">Guests</label>
                    <select id="guests" name="guests">
                        <?php for ($i = 1; $i <= 10; $i++): ?>
                            <option value="<?php echo $i; ?>" <?php echo ($guests == $i) ? 'selected' : ''; ?>>
                                <?php echo $i; ?> <?php echo ($i == 1) ? 'Guest' : 'Guests'; ?>
                            </option>
                        <?php endfor; ?>
                    </select>
                </div>
            </div>
            
            <div class="form-row">
                <div class="form-group">
                    <label for="min_price">Min Price ($)</label>
                    <input type="number" id="min_price" name="min_price" value="<?php echo htmlspecialchars($min_price); ?>" min="0" step="10">
                </div>
                
                <div class="form-group">
                    <label for="max_price">Max Price ($)</label>
                    <input type="number" id="max_price" name="max_price" value="<?php echo htmlspecialchars($max_price); ?>" min="0" step="10">
                </div>
            </div>
            
            <button type="submit">Search</button>
        </form>
        
        <div class="search-results">
            <h3>Available Hotels (<?php echo count($hotels); ?> found)</h3>
            
            <?php if (empty($hotels)): ?>
                <p>No hotels found matching your criteria. Please try different search parameters.</p>
            <?php else: ?>
                <?php foreach ($hotels as $hotel): ?>
                    <div class="hotel-card">
                        <h4><?php echo htmlspecialchars($hotel['name']); ?></h4>
                        <p class="location"><?php echo htmlspecialchars($hotel['city']); ?>, <?php echo htmlspecialchars($hotel['country']); ?></p>
                        <p class="description"><?php echo htmlspecialchars(substr($hotel['description'], 0, 150)); ?>...</p>
                        <p class="rating">Rating: <?php echo htmlspecialchars($hotel['rating']); ?>/5</p>
                        <?php if (!empty($hotel['pricing'])): ?>
                            <?php $pricing = json_decode($hotel['pricing'], true); ?>
                            <p class="price">From $<?php echo htmlspecialchars($pricing['min_price']); ?> to $<?php echo htmlspecialchars($pricing['max_price']); ?> per night</p>
                        <?php endif; ?>
                        <a href="hotel_profile.php?id=<?php echo $hotel['id']; ?>" class="btn">View Hotel</a>
                    </div>
                <?php endforeach; ?>
            <?php endif; ?>
        </div>
    </div>
</body>
</html>