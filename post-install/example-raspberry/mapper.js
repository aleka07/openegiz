function mapToDittoProtocolMsg(headers, textPayload, bytePayload, contentType) {
    const jsonData = JSON.parse(textPayload);

    const temperature = jsonData['temp'];
    const humidity = jsonData['hum'];
    const topic_split = headers['topic'].split('/');
    const id = topic_split[topic_split.length-1];
    
	const features = {
        temperature: {
            properties: {
                value: temperature,
                time: Date.now()
            }
        },
        humidity: {
            properties: {
                value: humidity,
                time: Date.now()
            }
        }
    };

    return Ditto.buildDittoProtocolMsg(
        'example',
        id, 
        'things',
        'twin',
        'commands',
        'modify',
        '/features',
        headers,
        features
    );
}