const express = require("express");
const cors = require("cors");
const axios = require("axios");

const app = express();
const PORT = process.env.PORT || 5000;

// Enable CORS for all requests
app.use(cors());

// Allow JSON body
app.use(express.json());

// Weather API route
app.get("/api/weather", async (req, res) => {
    const city = req.query.city;

    if (!city) {
        return res.status(400).json({ error: "City is required" });
    }

    try {
        const apiKey = "YOUR_OPENWEATHERMAP_KEY";

        const response = await axios.get(
            `https://api.openweathermap.org/data/2.5/weather?q=${city}&appid=${apiKey}&units=metric`
        );

        res.json(response.data);
    } catch (err) {
        res.status(500).json({ error: "Failed to fetch weather" });
    }
});

app.get("/", (req, res) => {
    res.send("Backend Working!");
});

app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});
