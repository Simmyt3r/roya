<?php
require_once '../includes/config.php';
require_once '../includes/database.php';
require_once '../includes/auth.php';

redirect_if_not_hotel_logged_in();

$db = new Database();

// Get hotel ID from session
$hotel_id = $_SESSION['hotel_id'];

// Fetch existing hotel profile data
$query = "SELECT * FROM hotel_profiles WHERE hotel_id = :hotel_id";
$db->query($query);
$db->bind(':hotel_id', $hotel_id);
$profile = $db->single();

// Handle form submission
if ($_SERVER['REQUEST_METHOD'] == 'POST') {
    $description = $_POST['description'];
    $amenities = $_POST['amenities'];
    $policies = $_POST['policies'];
    
    // Handle photo uploads (simplified for MVP)
    $photos = [];
    if (isset($_POST['photos'])) {
        $photos = explode(',', $_POST['photos']);
    }
    
    // Handle pricing (simplified for MVP)
    $pricing = [
        'min_price' => (float)$_POST['min_price'],
        'max_price' => (float)$_POST['max_price']
    ];
    
    // Handle availability (simplified for MVP)
    $availability = [
        'rooms_available' => (int)$_POST['rooms_available']
    ];
    
    $photos_json = json_encode($photos);
    $pricing_json = json_encode($pricing);
    $availability_json = json_encode($availability);
    
    if ($profile) {
        // Update existing profile
        $query = "UPDATE hotel_profiles 
                  SET photos = :photos, pricing = :pricing, availability = :availability, 
                      amenities = :amenities, policies = :policies
                  WHERE hotel_id = :hotel_id";
    } else {
        // Create new profile
        $query = "INSERT INTO hotel_profiles (hotel_id, photos, pricing, availability, amenities, policies) 
                  VALUES (:hotel_id, :photos, :pricing, :availability, :amenities, :policies)";
    }
    
    $db->query($query);
    $db->bind(':hotel_id', $hotel_id);
    $db->bind(':photos', $photos_json);
    $db->bind(':pricing', $pricing_json);
    $db->bind(':availability', $availability_json);
    $db->bind(':amenities', $amenities);
    $db->bind(':policies', $policies);
    
    if ($db->execute()) {
        $success = "Profile updated successfully!";
        // Refresh profile data
        $query = "SELECT * FROM hotel_profiles WHERE hotel_id = :hotel_id";
        $db->query($query);
        $db->bind(':hotel_id', $hotel_id);
        $profile = $db->single();
    } else {
        $error = "Failed to update profile. Please try again.";
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Profile Builder - <?php echo SITE_NAME; ?></title>
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
        
        <h2>Hotel Profile Builder</h2>
        
        <?php if (isset($success)): ?>
            <div class="success"><?php echo $success; ?></div>
        <?php endif; ?>
        
        <?php if (isset($error)): ?>
            <div class="error"><?php echo $error; ?></div>
        <?php endif; ?>
        
        <form method="POST" action="" class="profile-builder">
            <div class="form-group">
                <label for="description">Hotel Description</label>
                <textarea id="description" name="description" rows="5"><?php echo $profile ? htmlspecialchars($profile['description']) : ''; ?></textarea>
            </div>
            
            <div class="form-group">
                <label for="amenities">Amenities</label>
                <textarea id="amenities" name="amenities" rows="3"><?php echo $profile ? htmlspecialchars($profile['amenities']) : ''; ?></textarea>
            </div>
            
            <div class="form-group">
                <label for="policies">Policies</label>
                <textarea id="policies" name="policies" rows="3"><?php echo $profile ? htmlspecialchars($profile['policies']) : ''; ?></textarea>
            </div>
            
            <div class="form-row">
                <div class="form-group">
                    <label for="min_price">Minimum Price ($)</label>
                    <input type="number" id="min_price" name="min_price" min="0" step="1" 
                           value="<?php echo $profile && $profile['pricing'] ? json_decode($profile['pricing'], true)['min_price'] : ''; ?>">
                </div>
                
                <div class="form-group">
                    <label for="max_price">Maximum Price ($)</label>
                    <input type="number" id="max_price" name="max_price" min="0" step="1" 
                           value="<?php echo $profile && $profile['pricing'] ? json_decode($profile['pricing'], true)['max_price'] : ''; ?>">
                </div>
            </div>
            
            <div class="form-group">
                <label for="rooms_available">Rooms Available</label>
                <input type="number" id="rooms_available" name="rooms_available" min="0" step="1" 
                       value="<?php echo $profile && $profile['availability'] ? json_decode($profile['availability'], true)['rooms_available'] : ''; ?>">
            </div>
            
            <div class="form-group">
                <label>Photos (comma separated URLs)</label>
                <textarea name="photos" rows="3"><?php echo $profile && $profile['photos'] ? implode(',', json_decode($profile['photos'], true)) : ''; ?></textarea>
                <div class="photo-upload">
                    <?php if ($profile && $profile['photos']): ?>
                        <?php $photos = json_decode($profile['photos'], true); ?>
                        <?php foreach ($photos as $photo): ?>
                            <img src="<?php echo htmlspecialchars($photo); ?>" alt="Hotel photo">
                        <?php endforeach; ?>
                    <?php endif; ?>
                </div>
            </div>
            
            <button type="submit">Update Profile</button>
        </form>
    </div>
</body>
</html>