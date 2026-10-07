package ru.dewil.aicontrol;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.content.Context;
import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.GeneralSecurityException;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Blind public-contract checks against real app-private storage and AndroidKeyStore.
 * All capabilities are synthetic fixtures. No real credentials, key material,
 * production source reads, or mocked crypto are used.
 * INV-AUTHAND-02 INV-AUTHAND-04 INV-AUTHAND-05 INV-AUTHAND-06
 */
@RunWith(AndroidJUnit4.class)
public final class CredentialStoreTest {
    private static final String TOKEN = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
    private static final String OTHER_TOKEN = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB";
    private Context context;
    private File encrypted;
    private CredentialStore store;

    @Before
    public void preparePrivateFixture() throws Exception {
        context = ApplicationProvider.getApplicationContext();
        encrypted = new File(context.getNoBackupFilesDir(), "device-credential.enc");
        store = new CredentialStore(context);
        store.clear();
    }

    @After
    public void clearSyntheticCredential() throws Exception {
        try {
            new CredentialStore(context).clear();
        } finally {
            // Remove only this synthetic legacy-crash fixture if a RED assertion
            // or broken clear() leaves it behind, so following cases stay isolated.
            new File(encrypted.getParentFile(), encrypted.getName() + ".bak").delete();
        }
    }

    private void assertRecord(CredentialStore.Record record, String token, String state) {
        assertNotNull("Expected durable credential record", record);
        // Avoid printing capability values in assertion failure output.
        assertTrue("Credential token differs from saved synthetic value", token.equals(record.token));
        assertEquals(state, record.state);
    }

    @Test
    public void emptyStoreReturnsNoCredential() throws Exception {
        assertNull(store.load());
        assertNull(new CredentialStore(context).load());
    }

    @Test
    public void activeCredentialSurvivesStoreReconstruction() throws Exception {
        store.save(TOKEN, "ACTIVE");
        assertRecord(store.load(), TOKEN, "ACTIVE");
        assertRecord(new CredentialStore(context).load(), TOKEN, "ACTIVE");
        assertTrue("Encrypted credential must live in noBackupFilesDir", encrypted.isFile());
    }

    @Test
    public void pendingLogoutSurvivesReconstructionAndCannotBecomeActive() throws Exception {
        store.save(TOKEN, "ACTIVE");
        store.save(TOKEN, "PENDING_LOGOUT");
        assertRecord(new CredentialStore(context).load(), TOKEN, "PENDING_LOGOUT");
        assertRecord(new CredentialStore(context).load(), TOKEN, "PENDING_LOGOUT");
    }

    @Test
    public void overwritePersistsOnlyTheLatestCredential() throws Exception {
        store.save(TOKEN, "PENDING_LOGOUT");
        store.save(OTHER_TOKEN, "ACTIVE");
        assertRecord(new CredentialStore(context).load(), OTHER_TOKEN, "ACTIVE");
    }

    @Test
    public void clearDeletesDurableRecordAndIsIdempotent() throws Exception {
        store.save(TOKEN, "ACTIVE");
        new CredentialStore(context).clear();
        assertFalse("clear must delete encrypted record", encrypted.exists());
        assertNull(new CredentialStore(context).load());
        store.clear();
        assertNull(store.load());
    }

    @Test
    public void persistedBytesNeverContainPlaintextCapability() throws Exception {
        store.save(TOKEN, "ACTIVE");
        assertTrue("Encrypted record must exist after save", encrypted.isFile());
        byte[] bytes = Files.readAllBytes(encrypted.toPath());
        assertTrue("Encrypted record cannot be empty", bytes.length > 0);
        String raw = new String(bytes, StandardCharsets.ISO_8859_1);
        assertFalse("Plaintext capability found in encrypted record", raw.contains(TOKEN));
        store.save(OTHER_TOKEN, "PENDING_LOGOUT");
        raw = new String(Files.readAllBytes(encrypted.toPath()), StandardCharsets.ISO_8859_1);
        assertFalse("Old plaintext capability found in encrypted record", raw.contains(TOKEN));
        assertFalse("New plaintext capability found in encrypted record", raw.contains(OTHER_TOKEN));
    }

    @Test
    public void invalidStateIsRejectedWithoutLosingExistingCredential() throws Exception {
        store.save(TOKEN, "ACTIVE");
        for (String state : new String[] {"", "pending_logout", "REVOKED", "UNKNOWN", null}) {
            try {
                store.save(OTHER_TOKEN, state);
                fail("Unknown credential state must be rejected");
            } catch (IllegalArgumentException expected) {
                assertSafeException(expected);
            }
            assertRecord(new CredentialStore(context).load(), TOKEN, "ACTIVE");
        }
    }

    @Test
    public void truncatedRecordFailsClosedInsteadOfReturningActiveCredential() throws Exception {
        store.save(TOKEN, "ACTIVE");
        assertTrue("save must persist encrypted record", encrypted.isFile());
        Files.write(encrypted.toPath(), new byte[] {1, 2, 3});
        assertCorruptLoadRejected();
    }

    @Test
    public void tamperedCiphertextFailsClosed() throws Exception {
        store.save(TOKEN, "PENDING_LOGOUT");
        assertTrue("save must persist encrypted record", encrypted.isFile());
        byte[] bytes = Files.readAllBytes(encrypted.toPath());
        assertTrue("Encrypted record must have tamperable bytes", bytes.length > 0);
        bytes[bytes.length - 1] ^= 1;
        Files.write(encrypted.toPath(), bytes);
        assertCorruptLoadRejected();
    }

    @Test
    public void legacyAtomicBackupRestoresActiveCredentialAfterCrash() throws Exception {
        assertAtomicBackupRecovery("ACTIVE");
    }

    @Test
    public void legacyAtomicBackupKeepsPendingLogoutAfterCrash() throws Exception {
        assertAtomicBackupRecovery("PENDING_LOGOUT");
    }

    @Test
    public void clearDeletesLegacyBackupEvenWhenBaseRecordIsAbsent() throws Exception {
        store.save(TOKEN, "PENDING_LOGOUT");
        File backup = moveEncryptedRecordToLegacyBackup();
        new CredentialStore(context).clear();
        assertFalse("clear must delete the base record", encrypted.exists());
        assertFalse("clear must delete legacy backup without restoring admission", backup.exists());
        assertNull(new CredentialStore(context).load());
    }

    private void assertAtomicBackupRecovery(String state) throws Exception {
        store.save(TOKEN, state);
        File backup = moveEncryptedRecordToLegacyBackup();
        // AtomicFile documents recovery of backups produced by its former
        // implementation: https://developer.android.com/reference/android/util/AtomicFile
        assertRecord(new CredentialStore(context).load(), TOKEN, state);
        new CredentialStore(context).clear();
        assertFalse("clear must remove restored encrypted record", encrypted.exists());
        assertFalse("clear must remove legacy backup", backup.exists());
        assertNull(new CredentialStore(context).load());
    }

    private File moveEncryptedRecordToLegacyBackup() throws Exception {
        File[] records = context.getNoBackupFilesDir().listFiles(file ->
                file.isFile() && file.getName().equals("device-credential.enc"));
        assertNotNull("Private storage directory must be readable", records);
        assertEquals("Expected exactly one encrypted credential record", 1, records.length);
        File record = records[0];
        File backup = new File(record.getParentFile(), record.getName() + ".bak");
        assertFalse("Fixture starts without a legacy backup", backup.exists());
        Files.move(record.toPath(), backup.toPath());
        assertFalse("Crash fixture has no base record", record.exists());
        assertTrue("Crash fixture retains encrypted backup", backup.isFile());
        return backup;
    }

    private void assertCorruptLoadRejected() throws Exception {
        try {
            new CredentialStore(context).load();
            fail("Corrupt credential must raise a checked storage/crypto exception");
        } catch (IOException | GeneralSecurityException expected) {
            assertSafeException(expected);
        }
    }

    private void assertSafeException(Exception error) {
        String message = String.valueOf(error.getMessage());
        assertFalse("Storage error must not expose saved capability", message.contains(TOKEN));
        assertFalse("Storage error must not expose replacement capability", message.contains(OTHER_TOKEN));
    }
}
