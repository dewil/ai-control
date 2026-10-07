package ru.dewil.aicontrol;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** INV-AUTHAND-02/05/06: only encrypted capabilities in app-private no-backup storage. */
public final class CredentialStore {
    public static final class Record {
        public final String token, state;
        public Record(String token, String state) { this.token=token; this.state=state; }
    }
    private static final String ALIAS="ai-control-device-token";
    private final AtomicFile file;
    public CredentialStore(Context context) {
        file=new AtomicFile(new File(context.getNoBackupFilesDir(),"device-credential.enc"));
    }
    private SecretKey key(boolean create) throws GeneralSecurityException, IOException {
        KeyStore keys=KeyStore.getInstance("AndroidKeyStore");
        keys.load(null);
        if (!keys.containsAlias(ALIAS)) {
            if (!create) throw new GeneralSecurityException("Saved credential unavailable");
            KeyGenerator generator=KeyGenerator.getInstance("AES","AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256).build());
            return generator.generateKey();
        }
        return (SecretKey)keys.getKey(ALIAS,null);
    }
    public synchronized Record load() throws IOException,GeneralSecurityException {
        try (DataInputStream in=new DataInputStream(file.openRead())) {
            int size=in.readUnsignedByte();
            if (size!=12) throw new IOException("Saved credential unavailable");
            byte[] iv=new byte[size]; in.readFully(iv);
            ByteArrayOutputStream bounded=new ByteArrayOutputStream();
            byte[] buffer=new byte[512];int count;
            while((count=in.read(buffer))!=-1){if(bounded.size()+count>4096)throw new IOException("Saved credential unavailable");bounded.write(buffer,0,count);}
            byte[] encrypted=bounded.toByteArray();
            if(encrypted.length<16 || encrypted.length>4096) throw new IOException("Saved credential unavailable");
            Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE,key(false),new GCMParameterSpec(128,iv));
            JSONObject data=new JSONObject(new String(cipher.doFinal(encrypted),StandardCharsets.UTF_8));
            String token=data.getString("token"),state=data.getString("state");
            validate(token,state);
            return new Record(token,state);
        } catch (FileNotFoundException error) {
            if (file.getBaseFile().exists() || new File(file.getBaseFile()+".bak").exists() || new File(file.getBaseFile()+".new").exists())
                throw new IOException("Saved credential unavailable");
            return null;
        } catch (IOException|GeneralSecurityException error) { throw error; }
        catch (Exception error) { throw new IOException("Saved credential unavailable"); }
    }
    private static void validate(String token,String state) {
        if(token==null || !token.matches("[A-Za-z0-9_-]{43}") ||
            !("ACTIVE".equals(state)||"PENDING_LOGOUT".equals(state)))
            throw new IllegalArgumentException("Invalid credential record");
    }
    public synchronized void save(String token,String state) throws IOException,GeneralSecurityException {
        validate(token,state);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,key(true));
        byte[] encrypted;
        try { encrypted=cipher.doFinal(new JSONObject().put("token",token).put("state",state)
                                      .toString().getBytes(StandardCharsets.UTF_8)); }
        catch(org.json.JSONException error) { throw new IOException("Saved credential unavailable"); }
        FileOutputStream raw=null;
        try {
            raw=file.startWrite();
            raw.write(cipher.getIV().length); raw.write(cipher.getIV()); raw.write(encrypted);
            file.finishWrite(raw);
        } catch(IOException error) { if(raw!=null)file.failWrite(raw); throw error; }
    }
    public synchronized void clear() throws IOException,GeneralSecurityException {
        file.delete();
        if(file.getBaseFile().exists() || new File(file.getBaseFile()+".bak").exists() || new File(file.getBaseFile()+".new").exists())throw new IOException("Saved credential unavailable");
    }
}
